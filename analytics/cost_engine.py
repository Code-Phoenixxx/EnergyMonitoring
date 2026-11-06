"""Cost calculation and carbon footprint engine based on YAML tariff parameters."""

from datetime import datetime, time
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import yaml

from simulator.config_loader import load_yaml

logger = logging.getLogger("cost_engine")


class CostAndCarbonEngine:
    """Calculates Time-of-Day electrical energy cost (INR) and carbon emissions (kg CO2)."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        """Initialize engine with tariffs.yaml and emissions.yaml configurations."""
        if config_dir is None:
            config_dir = Path("config")

        self.tariffs_cfg = load_yaml(config_dir / "tariffs.yaml")
        self.emissions_cfg = load_yaml(config_dir / "emissions.yaml")

        # Load grid emissions factor (default 0.82 kg CO2 / kWh, CEA India)
        self.kg_co2_per_kwh = float(
            self.emissions_cfg.get("grid_emissions", {}).get("factor_kg_co2_per_kwh", 0.82)
        )

        # Parse ToD slots
        self.slots = self.tariffs_cfg.get("time_of_day_slots", [])
        self.demand_charges = self.tariffs_cfg.get("demand_charges", {})
        self.taxes = self.tariffs_cfg.get("taxes_and_cess", {})

    @staticmethod
    def _parse_time(time_str: str) -> time:
        hour, minute = map(int, time_str.split(":"))
        return time(hour, minute)

    def is_in_slot(self, t: time, start: time, end: time) -> bool:
        """Check if time t falls within start and end boundaries (handling midnight rollover)."""
        if start <= end:
            return start <= t < end
        return t >= start or t < end

    def get_tod_rate(self, dt: datetime) -> Tuple[str, float]:
        """Determine Time-of-Day slot name and active rate in INR/kWh for a given timestamp.

        Args:
            dt: Target datetime to evaluate.

        Returns:
            Tuple of (slot_name, rate_inr_per_kwh).
        """
        current_time = dt.time()
        for slot in self.slots:
            start_t = self._parse_time(slot["start_time"])
            end_t = self._parse_time(slot["end_time"])
            if self.is_in_slot(current_time, start_t, end_t):
                return slot["name"], float(slot["rate_inr_per_kwh"])

        # Fallback to default normal rate if slot not matched
        return "normal", 7.80

    def calculate_cost(self, kwh: float, dt: Optional[datetime] = None) -> float:
        """Calculate energy charge in INR for a given kWh consumption.

        Args:
            kwh: Energy consumed in Kilowatt-hours.
            dt: Timestamp for Time-of-Day slot determination (defaults to now).

        Returns:
            Total energy cost in INR including fuel adjustment surcharge.
        """
        if kwh <= 0.0:
            return 0.0

        if dt is None:
            dt = datetime.now()

        slot_name, base_rate = self.get_tod_rate(dt)
        fppca = float(self.taxes.get("fuel_surcharge_inr_per_kwh", 0.65))
        effective_rate = base_rate + fppca

        base_cost = kwh * effective_rate
        duty_pct = float(self.taxes.get("electricity_duty_pct", 0.093))
        total_cost = base_cost * (1.0 + duty_pct)

        return round(total_cost, 2)

    def calculate_co2(self, kwh: float) -> float:
        """Calculate carbon footprint in kilograms of CO2 for a given kWh.

        Args:
            kwh: Energy consumed in Kilowatt-hours.

        Returns:
            CO2 emissions in kilograms (kg CO2).
        """
        return round(max(0.0, kwh) * self.kg_co2_per_kwh, 3)

    def calculate_demand_penalty(self, max_demand_kva: float) -> float:
        """Calculate maximum demand penalty in INR if contract demand is breached."""
        contract_demand = float(self.demand_charges.get("contract_demand_kva", 280.0))
        rate_per_kva = float(self.demand_charges.get("rate_inr_per_kva_per_month", 450.0))
        penalty_mult = float(self.demand_charges.get("excess_demand_penalty_multiplier", 1.5))

        if max_demand_kva > contract_demand:
            excess_kva = max_demand_kva - contract_demand
            penalty_inr = excess_kva * rate_per_kva * penalty_mult
            return round(penalty_inr, 2)
        return 0.0

