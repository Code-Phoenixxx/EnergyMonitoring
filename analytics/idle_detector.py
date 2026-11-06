"""Idle power wastage detection module."""

from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from analytics.cost_engine import CostAndCarbonEngine
from database.models import TelemetryRecord, WasteEventRecord
from simulator.config_loader import load_machines_config, load_yaml

logger = logging.getLogger("idle_detector")


class IdleWasteDetector:
    """Detects unnecessary energy wastage from machines idling or drawing power while off."""

    def __init__(self, config_dir: Optional[Path] = None, cost_engine: Optional[CostAndCarbonEngine] = None) -> None:
        if config_dir is None:
            config_dir = Path("config")

        self.thresholds_cfg = load_yaml(config_dir / "thresholds.yaml")
        self.machines_cfg = load_machines_config(config_dir)
        self.cost_engine = cost_engine or CostAndCarbonEngine(config_dir)

        # Parse idle wastage thresholds
        idle_cfg = self.thresholds_cfg.get("idle_wastage", {})
        self.min_duration_minutes = float(idle_cfg.get("min_idle_duration_minutes", 10.0))
        self.default_pct_threshold = float(idle_cfg.get("default_idle_draw_pct_threshold", 0.15))
        self.machine_overrides: Dict[str, float] = idle_cfg.get("machine_idle_pct_thresholds", {})

        # In-memory tracking of ongoing idle periods: machine_id -> state tracking dict
        self.active_idle_periods: Dict[str, Dict] = {}

    def get_idle_power_limit_kw(self, machine_id: str) -> float:
        """Calculate maximum acceptable idle power before flagging as waste."""
        mcfg = self.machines_cfg.get(machine_id)
        if not mcfg:
            return 5.0  # Safe default 5 kW

        pct = self.machine_overrides.get(machine_id, self.default_pct_threshold)
        return mcfg.rated_power_kw * pct

    def inspect_reading(
        self,
        machine_id: str,
        state: str,
        power_kw: float,
        timestamp: datetime,
        db: Optional[Session] = None,
    ) -> Optional[WasteEventRecord]:
        """Evaluate a single machine telemetry reading for idle waste conditions.

        Args:
            machine_id: Target machine identifier.
            state: Operating state (OFF, IDLE, RUNNING, FAULT).
            power_kw: Current active power in kW.
            timestamp: Observation timestamp.
            db: Optional database session to persist detected events.

        Returns:
            WasteEventRecord if an idle waste period concluded or was flagged, else None.
        """
        limit_kw = self.get_idle_power_limit_kw(machine_id)
        is_idle_or_off = state.upper() in ("IDLE", "OFF")
        is_drawing_waste = is_idle_or_off and (power_kw > limit_kw)

        event_to_record = None

        if is_drawing_waste:
            if machine_id not in self.active_idle_periods:
                # Start new idle tracking window
                self.active_idle_periods[machine_id] = {
                    "start_time": timestamp,
                    "last_time": timestamp,
                    "accumulated_kwh": 0.0,
                    "peak_power_kw": power_kw,
                    "samples": 1,
                    "state": state,
                }
            else:
                track = self.active_idle_periods[machine_id]
                delta_hours = max(0.0, (timestamp - track["last_time"]).total_seconds() / 3600.0)
                track["accumulated_kwh"] += power_kw * delta_hours
                track["last_time"] = timestamp
                track["peak_power_kw"] = max(track["peak_power_kw"], power_kw)
                track["samples"] += 1

                duration_mins = (timestamp - track["start_time"]).total_seconds() / 60.0

                # If duration exceeded threshold and event not yet emitted
                if duration_mins >= self.min_duration_minutes and not track.get("emitted", False):
                    wasted_kwh = track["accumulated_kwh"]
                    cost_inr = self.cost_engine.calculate_cost(wasted_kwh, timestamp)
                    severity = "HIGH" if wasted_kwh > 50.0 else "MEDIUM"
                    desc = (
                        f"Machine '{machine_id}' in {state} state exceeded idle threshold "
                        f"({limit_kw:.1f} kW) for {duration_mins:.1f} min drawing {power_kw:.1f} kW."
                    )
                    event_to_record = WasteEventRecord(
                        event_type="IDLE_WASTE",
                        machine_id=machine_id,
                        start_time=track["start_time"],
                        end_time=timestamp,
                        kwh_wasted=round(wasted_kwh, 3),
                        cost_inr=round(cost_inr, 2),
                        severity=severity,
                        description=desc,
                    )
                    track["emitted"] = True

        else:
            # Machine returned to normal RUNNING or stopped drawing power
            if machine_id in self.active_idle_periods:
                track = self.active_idle_periods.pop(machine_id)
                duration_mins = (track["last_time"] - track["start_time"]).total_seconds() / 60.0
                if duration_mins >= self.min_duration_minutes and not track.get("emitted", False):
                    wasted_kwh = track["accumulated_kwh"]
                    cost_inr = self.cost_engine.calculate_cost(wasted_kwh, track["last_time"])
                    severity = "HIGH" if wasted_kwh > 50.0 else "MEDIUM"
                    desc = (
                        f"Machine '{machine_id}' was left idling with high draw ({track['peak_power_kw']:.1f} kW peak) "
                        f"for {duration_mins:.1f} minutes."
                    )
                    event_to_record = WasteEventRecord(
                        event_type="IDLE_WASTE",
                        machine_id=machine_id,
                        start_time=track["start_time"],
                        end_time=track["last_time"],
                        kwh_wasted=round(wasted_kwh, 3),
                        cost_inr=round(cost_inr, 2),
                        severity=severity,
                        description=desc,
                    )

        if event_to_record and db:
            db.add(event_to_record)
            db.commit()
            logger.warning(f"Detected Idle Waste on {machine_id}: {event_to_record.description}")

        return event_to_record

