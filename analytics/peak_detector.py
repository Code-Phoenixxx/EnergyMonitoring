"""Rolling 15-minute peak demand and plant capacity breach detector."""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.cost_engine import CostAndCarbonEngine
from database.models import WasteEventRecord
from simulator.config_loader import load_yaml

logger = logging.getLogger("peak_detector")


class PeakDemandDetector:
    """Monitors rolling 15-minute active plant power against contract demand limits."""

    def __init__(self, config_dir: Optional[Path] = None, cost_engine: Optional[CostAndCarbonEngine] = None) -> None:
        if config_dir is None:
            config_dir = Path("config")

        self.thresholds_cfg = load_yaml(config_dir / "thresholds.yaml")
        self.cost_engine = cost_engine or CostAndCarbonEngine(config_dir)

        plant_cfg = self.thresholds_cfg.get("plant_limits", {})
        self.max_demand_threshold_kw = float(plant_cfg.get("max_demand_threshold_kw", 250.0))
        self.warning_demand_threshold_kw = float(plant_cfg.get("warning_demand_threshold_kw", 220.0))
        self.window_minutes = int(plant_cfg.get("rolling_window_minutes", 15))

        self.last_breach_alert_time: Optional[datetime] = None

    def evaluate_rolling_demand(self, db: Session, current_time: Optional[datetime] = None) -> Optional[WasteEventRecord]:
        """Compute current 15-minute average demand across all machines and detect breaches.

        Args:
            db: Database session.
            current_time: Reference timestamp (defaults to current time).

        Returns:
            WasteEventRecord if peak demand limit was breached, else None.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        window_start = current_time - timedelta(minutes=self.window_minutes)

        # Query average plant power in the window
        sql = text("""
            SELECT AVG(plant_power) AS rolling_avg_kw, MAX(plant_power) AS peak_kw
            FROM (
                SELECT time, SUM(power_kw) AS plant_power
                FROM telemetry
                WHERE time >= :window_start AND time <= :current_time
                GROUP BY time
            ) plant_samples;
        """)

        result = db.execute(sql, {"window_start": window_start, "current_time": current_time}).fetchone()

        if not result or result[0] is None:
            return None

        rolling_avg_kw = float(result[0])
        peak_kw = float(result[1] or rolling_avg_kw)

        if rolling_avg_kw > self.max_demand_threshold_kw:
            # Throttle repetitive alert events within the same 15-min window
            if self.last_breach_alert_time and (current_time - self.last_breach_alert_time).total_seconds() < 900:
                return None

            excess_kw = rolling_avg_kw - self.max_demand_threshold_kw
            # Assume 0.90 power factor to estimate kVA demand surcharge
            excess_kva = excess_kw / 0.90
            penalty_cost = self.cost_engine.calculate_demand_penalty(excess_kva + 280.0)

            severity = "CRITICAL" if rolling_avg_kw > (self.max_demand_threshold_kw * 1.15) else "HIGH"
            desc = (
                f"Plant Peak Demand Breach! 15-min rolling average reached {rolling_avg_kw:.1f} kW "
                f"(Instantaneous peak: {peak_kw:.1f} kW), exceeding contract threshold of {self.max_demand_threshold_kw:.1f} kW. "
                f"Excess demand: {excess_kw:.1f} kW (~{excess_kva:.1f} kVA)."
            )

            # Wasted energy approximation during breach window (15 mins = 0.25h)
            wasted_kwh = excess_kw * (self.window_minutes / 60.0)

            event = WasteEventRecord(
                event_type="PEAK_DEMAND",
                machine_id="PLANT",
                start_time=window_start,
                end_time=current_time,
                kwh_wasted=round(wasted_kwh, 3),
                cost_inr=round(penalty_cost, 2),
                severity=severity,
                description=desc,
            )

            db.add(event)
            db.commit()
            self.last_breach_alert_time = current_time
            logger.error(f"[PEAK BREACH] {desc}")
            return event

        return None

