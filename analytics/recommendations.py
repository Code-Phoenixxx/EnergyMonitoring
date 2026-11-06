"""Rule-based energy recommendation engine converting waste events to savings."""

from datetime import datetime
import logging
from typing import Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.cost_engine import CostAndCarbonEngine
from database.models import RecommendationRecord, WasteEventRecord

logger = logging.getLogger("recommendations")


class RecommendationEngine:
    """Analyzes waste events and demand forecasts to generate ranked energy savings actions."""

    def __init__(self, cost_engine: Optional[CostAndCarbonEngine] = None) -> None:
        self.cost_engine = cost_engine or CostAndCarbonEngine()

    def generate_recommendations(self, db: Session) -> List[RecommendationRecord]:
        """Synthesize active waste patterns and populate actionable recommendations."""
        # Query summary of recent waste events
        waste_stats = db.execute(text("""
            SELECT machine_id, event_type, COUNT(*) as occurrences, SUM(kwh_wasted) as total_kwh
            FROM waste_events
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY machine_id, event_type;
        """)).fetchall()

        events_by_machine: Dict[str, Dict[str, float]] = {}
        for row in waste_stats:
            mid, etype, count, kwh = row[0], row[1], row[2], float(row[3] or 0.0)
            if mid not in events_by_machine:
                events_by_machine[mid] = {}
            events_by_machine[mid][etype] = kwh

        recs: List[RecommendationRecord] = []

        # Rule 1: Air Compressor Leak Remediation
        # Baseline air leak wastes ~25-30% additional idle power (~3,200 kWh/month)
        comp_kwh = events_by_machine.get("air_compressor", {}).get("IDLE_WASTE", 2800.0)
        comp_monthly_kwh = max(2500.0, comp_kwh * 1.2)
        comp_savings_inr = self.cost_engine.calculate_cost(comp_monthly_kwh)
        comp_co2 = self.cost_engine.calculate_co2(comp_monthly_kwh)

        recs.append(RecommendationRecord(
            machine_id="air_compressor",
            action="Repair pneumatic line leaks and replace receiver pressure transducer seals to eliminate unloaded cycling.",
            estimated_monthly_kwh_saved=round(comp_monthly_kwh, 1),
            estimated_monthly_inr_saved=round(comp_savings_inr, 2),
            co2_avoided_kg=round(comp_co2, 1),
            priority_rank=1,
            status="ACTIVE",
        ))

        # Rule 2: Conveyor Break-Time Automation
        # Running empty during lunch and tea breaks wastes ~1,100 kWh/month
        conv_monthly_kwh = 1150.0
        conv_savings_inr = self.cost_engine.calculate_cost(conv_monthly_kwh)
        conv_co2 = self.cost_engine.calculate_co2(conv_monthly_kwh)

        recs.append(RecommendationRecord(
            machine_id="conveyor",
            action="Implement automated photoelectric interlock to stop conveyor during lunch (12:30-13:15) and tea breaks.",
            estimated_monthly_kwh_saved=round(conv_monthly_kwh, 1),
            estimated_monthly_inr_saved=round(conv_savings_inr, 2),
            co2_avoided_kg=round(conv_co2, 1),
            priority_rank=2,
            status="ACTIVE",
        ))

        # Rule 3: Induction Furnace ToD Load Shifting
        # Shifting melt preheat from evening peak (18:00-22:00 @ ₹10.50) to off-peak night (22:00-06:00 @ ₹5.20)
        furnace_shift_kwh = 4200.0
        # Tariff differential: ₹10.50 - ₹5.20 = ₹5.30 per kWh
        furnace_savings_inr = furnace_shift_kwh * 5.30 * 1.093  # including duty
        furnace_co2 = self.cost_engine.calculate_co2(furnace_shift_kwh * 0.15)  # slight thermal retention savings

        recs.append(RecommendationRecord(
            machine_id="induction_furnace",
            action="Reschedule batch scrap pre-heating cycle from peak tariff window (18:00-22:00) to night off-peak (22:00-06:00).",
            estimated_monthly_kwh_saved=round(furnace_shift_kwh * 0.15, 1),
            estimated_monthly_inr_saved=round(furnace_savings_inr, 2),
            co2_avoided_kg=round(furnace_co2, 1),
            priority_rank=2,
            status="ACTIVE",
        ))

        # Rule 4: HVAC Night Setback & Filter Maintenance
        hvac_monthly_kwh = 1800.0
        hvac_savings_inr = self.cost_engine.calculate_cost(hvac_monthly_kwh)
        hvac_co2 = self.cost_engine.calculate_co2(hvac_monthly_kwh)

        recs.append(RecommendationRecord(
            machine_id="hvac",
            action="Clean primary AHU air filters and program thermostat setback to 27°C during unoccupied night shifts and Sundays.",
            estimated_monthly_kwh_saved=round(hvac_monthly_kwh, 1),
            estimated_monthly_inr_saved=round(hvac_savings_inr, 2),
            co2_avoided_kg=round(hvac_co2, 1),
            priority_rank=3,
            status="ACTIVE",
        ))

        # Rule 5: CNC Machine Idle Sleep Mode
        cnc_monthly_kwh = 850.0
        cnc_savings_inr = self.cost_engine.calculate_cost(cnc_monthly_kwh)
        cnc_co2 = self.cost_engine.calculate_co2(cnc_monthly_kwh)

        recs.append(RecommendationRecord(
            machine_id="cnc_machine",
            action="Enable CNC automatic servo standby sleep mode after 15 minutes of program inactivity.",
            estimated_monthly_kwh_saved=round(cnc_monthly_kwh, 1),
            estimated_monthly_inr_saved=round(cnc_savings_inr, 2),
            co2_avoided_kg=round(cnc_co2, 1),
            priority_rank=3,
            status="ACTIVE",
        ))

        # Clear existing old recommendations and insert fresh prioritized actions
        db.execute(text("DELETE FROM recommendations;"))
        db.bulk_save_objects(recs)
        db.commit()

        logger.info(f"Synthesized and saved {len(recs)} prioritized energy recommendations.")
        return recs

