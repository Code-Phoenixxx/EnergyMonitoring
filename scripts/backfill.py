"""Backfill script generating 60 days of historical machine telemetry for training."""

import argparse
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from typing import List

from database.connection import SessionLocal, init_db
from database.models import TelemetryRecord
from simulator.config_loader import load_machines_config, load_simulator_config
from simulator.faults import FaultManager
from simulator.machine import SimulatedMachine
from simulator.models import MachineState
from simulator.shift_manager import ShiftManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [backfill] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backfill")


def generate_backfill_data(days: int = 60, interval_minutes: int = 15) -> None:
    """Generate and batch insert N days of historical telemetry into TimescaleDB."""
    init_db()
    config_dir = Path("config")
    machines_cfg = load_machines_config(config_dir)
    sim_cfg = load_simulator_config(config_dir)

    shift_mgr = ShiftManager(sim_cfg)
    fault_mgr = FaultManager(enable_faults=True)

    # Seed baseline fault patterns
    fault_mgr.activate_fault("air_compressor", "air_leak")
    fault_mgr.activate_fault("conveyor", "motor_degradation")

    machines = {
        mid: SimulatedMachine(mcfg, initial_energy_kwh=1000.0)
        for mid, mcfg in machines_cfg.items()
    }

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=days)
    current_time = start_time
    step_seconds = interval_minutes * 60

    total_steps = int((days * 24 * 60) / interval_minutes)
    logger.info(f"Generating {days} days of history ({total_steps} time steps across 6 machines)...")

    db = SessionLocal()
    batch_records: List[TelemetryRecord] = []
    inserted_count = 0

    try:
        step = 0
        while current_time < now:
            step += 1
            current_time += timedelta(seconds=step_seconds)
            elapsed_hours = step_seconds / 3600.0

            for mid, mach in machines.items():
                fault_mgr.update_degradation(mid, elapsed_hours)
                nominal_state = shift_mgr.determine_nominal_state(mid, current_time)

                state_prof = mach.config.states.get(nominal_state.value)
                approx_power = (
                    mach.config.rated_power_kw * (state_prof.load_pct_max + state_prof.load_pct_min) / 2.0
                    if state_prof and nominal_state.value != "OFF"
                    else 0.0
                )

                eff_state, eff_power, fault_note = fault_mgr.apply_fault_effects(
                    mid, nominal_state, approx_power, current_time
                )
                forced = eff_power if fault_note else None

                t = mach.step(eff_state, current_time, step_seconds, forced_power_kw=forced)

                batch_records.append(
                    TelemetryRecord(
                        time=current_time,
                        machine_id=mid,
                        state=t.state,
                        voltage=t.voltage,
                        current=t.current,
                        power_kw=t.power_kw,
                        power_factor=t.power_factor,
                        energy_kwh=t.energy_kwh,
                    )
                )

            if len(batch_records) >= 2000:
                db.bulk_save_objects(batch_records)
                db.commit()
                inserted_count += len(batch_records)
                batch_records.clear()
                progress_pct = (step / total_steps) * 100.0
                logger.info(f"Progress: {progress_pct:.1f}% ({inserted_count} records inserted)")

        if batch_records:
            db.bulk_save_objects(batch_records)
            db.commit()
            inserted_count += len(batch_records)

        logger.info(f"Backfill successfully completed! Total records inserted: {inserted_count}")

    except Exception as e:
        db.rollback()
        logger.error(f"Backfill encountered an error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate historical machine telemetry data")
    parser.add_argument("--days", type=int, default=60, help="Days of history to backfill (default: 60)")
    parser.add_argument("--interval", type=int, default=15, help="Step interval in minutes (default: 15)")
    args = parser.parse_args()
    generate_backfill_data(days=args.days, interval_minutes=args.interval)
