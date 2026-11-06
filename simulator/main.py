"""Main executable entrypoint for the virtual factory machine telemetry simulator."""

import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sys
import time
from typing import Dict
from dotenv import load_dotenv

load_dotenv()

from simulator.config_loader import load_machines_config, load_simulator_config
from simulator.faults import FaultManager
from simulator.machine import SimulatedMachine
from simulator.models import MachineTelemetry
from simulator.publisher import TelemetryPublisher, TelemetrySubscriber
from simulator.shift_manager import ShiftManager

# Configure standardized structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("simulator")


def build_arg_parser() -> argparse.ArgumentParser:
    """Build command line argument parser for the simulator CLI."""
    parser = argparse.ArgumentParser(
        description="Smart Industrial Virtual Factory Telemetry Simulator"
    )
    parser.add_argument(
        "--speedup",
        type=float,
        default=1.0,
        help="Simulation time speedup multiplier (e.g. 60.0 simulates 1 minute per real second, default: 1.0)",
    )
    parser.add_argument(
        "--broker",
        type=str,
        default=os.getenv("MQTT_BROKER_HOST", "127.0.0.1"),
        help="MQTT broker hostname or IP address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MQTT_BROKER_PORT", "1883")),
        help="MQTT broker port (default: 1883)",
    )
    parser.add_argument(
        "--config-dir",
        type=str,
        default="config",
        help="Path to directory containing YAML configurations (default: config)",
    )
    parser.add_argument(
        "--inject-faults",
        action="store_true",
        default=True,
        help="Enable fault injection scenarios (air leak, degradation, overnight idle, spikes)",
    )
    parser.add_argument(
        "--no-faults",
        action="store_false",
        dest="inject_faults",
        help="Disable all fault injection scenarios",
    )
    parser.add_argument(
        "--step-count",
        type=int,
        default=0,
        help="Run exactly N cycles and exit (default: 0 = run indefinitely)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Run for at most N real-time seconds and exit (default: 0.0 = unlimited)",
    )
    parser.add_argument(
        "--verify-samples",
        action="store_true",
        help="Run subscriber tap to capture and print sample messages arriving on factory/+/telemetry",
    )
    return parser


def run_simulator(args: argparse.Namespace) -> None:
    """Run the virtual factory simulation loop."""
    config_path = Path(args.config_dir)
    logger.info(f"Loading configuration from directory: {config_path.resolve()}")

    machines_cfg = load_machines_config(config_path)
    sim_cfg = load_simulator_config(config_path)

    base_interval = float(sim_cfg.get("mqtt", {}).get("publish_interval_seconds", 2.0))
    speedup = max(0.1, float(args.speedup))
    effective_sleep = max(0.001, base_interval / speedup)

    logger.info(
        f"Simulator configuration: {len(machines_cfg)} machines loaded. "
        f"Publish interval: {base_interval}s sim-time (speedup x{speedup:.1f} -> {effective_sleep:.3f}s real sleep per loop)"
    )

    # Initialize shift manager and fault manager
    shift_mgr = ShiftManager(sim_cfg)
    fault_mgr = FaultManager(enable_faults=args.inject_faults)

    # Seed initial realistic faults for demonstration
    if args.inject_faults:
        fault_mgr.activate_fault("air_compressor", "air_leak")
        fault_mgr.activate_fault("conveyor", "motor_degradation")
        fault_mgr.activate_fault("hvac", "cooling_empty_building")
        logger.info("Fault scenarios primed: air_compressor (air_leak), conveyor (motor_degradation), hvac (cooling_empty_building)")

    # Instantiate simulated machines
    machines: Dict[str, SimulatedMachine] = {}
    for mid, mcfg in machines_cfg.items():
        machines[mid] = SimulatedMachine(
            config=mcfg,
            noise_std_pct=sim_cfg.get("simulation", {}).get("gaussian_noise_std_pct", 0.02),
            voltage_variation_std_pct=sim_cfg.get("simulation", {}).get("voltage_variation_std_pct", 0.015),
            initial_energy_kwh=100.0,  # Baseline starting meter reading
        )

    # Setup telemetry publisher
    publisher = TelemetryPublisher(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=sim_cfg.get("mqtt", {}).get("client_id", "factory_simulator"),
        topic_template=sim_cfg.get("mqtt", {}).get("topic_template", "factory/{machine_id}/telemetry"),
    )

    connected = publisher.connect()
    if not connected:
        logger.warning(
            f"MQTT Broker at {args.broker}:{args.port} is not reachable. Telemetry will still generate in offline mode."
        )

    # Optional subscriber for verification
    verifier: Optional[TelemetrySubscriber] = None
    if args.verify_samples and connected:
        verifier = TelemetrySubscriber(broker_host=args.broker, broker_port=args.port)
        verifier.start()
        time.sleep(0.5)

    current_sim_dt = datetime.now(timezone.utc)
    cycle = 0
    start_time = time.time()

    logger.info("Starting factory telemetry emission loop...")
    try:
        while True:
            cycle += 1
            # Advance simulation time by base_interval
            sim_step_seconds = base_interval
            current_sim_dt += timedelta(seconds=sim_step_seconds)
            elapsed_sim_hours = sim_step_seconds / 3600.0

            total_kw = 0.0
            published_batch = []

            for mid, mach in machines.items():
                fault_mgr.update_degradation(mid, elapsed_sim_hours)
                nominal_state = shift_mgr.determine_nominal_state(mid, current_sim_dt)

                # Get tentative base power
                state_prof = mach.config.states.get(nominal_state.value)
                approx_power = (
                    mach.config.rated_power_kw * (state_prof.load_pct_max + state_prof.load_pct_min) / 2.0
                    if state_prof and nominal_state.value != "OFF"
                    else 0.0
                )

                # Apply fault effects
                eff_state, eff_power, fault_note = fault_mgr.apply_fault_effects(
                    mid, nominal_state, approx_power, current_sim_dt
                )

                forced_power = eff_power if fault_note else None
                telemetry = mach.step(
                    target_state=eff_state,
                    dt=current_sim_dt,
                    elapsed_seconds=sim_step_seconds,
                    forced_power_kw=forced_power,
                )

                total_kw += telemetry.power_kw
                published_batch.append(telemetry)

                if connected:
                    publisher.publish(telemetry)

            # Cycle summary log
            logger.info(
                f"[Cycle {cycle}] Sim Time: {current_sim_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                f"Plant Total: {total_kw:.2f} kW | "
                + " | ".join(f"{t.machine_id}: {t.power_kw:.1f}kW({t.state})" for t in published_batch)
            )

            # Check termination criteria
            if args.step_count > 0 and cycle >= args.step_count:
                logger.info(f"Reached requested step count ({args.step_count}). Exiting.")
                break

            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                logger.info(f"Reached requested duration ({args.duration}s). Exiting.")
                break

            time.sleep(effective_sleep)

    except KeyboardInterrupt:
        logger.info("Simulation halted by user keyboard interrupt.")
    finally:
        if verifier:
            time.sleep(0.5)
            verifier.stop()
        if connected:
            publisher.disconnect()


if __name__ == "__main__":
    parser = build_arg_parser()
    cli_args = parser.parse_args()
    run_simulator(cli_args)
