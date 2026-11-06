"""Unit tests for the Time-of-Day cost engine and carbon footprint calculations."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from analytics.cost_engine import CostAndCarbonEngine


@pytest.fixture
def cost_engine() -> CostAndCarbonEngine:
    return CostAndCarbonEngine(Path("config"))


class TestCostEngine:
    """Test suite for ToD tariffs, duties, surcharges, and CO2 math."""

    def test_tod_slots_recognition(self, cost_engine: CostAndCarbonEngine) -> None:
        """Verify that peak, normal, and off-peak hours map to configured tariff rates."""
        # 04:00 -> Off-peak (22:00 - 06:00 @ ₹5.20)
        dt_offpeak = datetime(2026, 11, 4, 4, 0, 0, tzinfo=timezone.utc)
        slot, rate = cost_engine.get_tod_rate(dt_offpeak)
        assert slot == "off_peak"
        assert rate == 5.20

        # 11:00 -> Normal (06:00 - 18:00 @ ₹7.80)
        dt_normal = datetime(2026, 11, 4, 11, 0, 0, tzinfo=timezone.utc)
        slot, rate = cost_engine.get_tod_rate(dt_normal)
        assert slot == "normal"
        assert rate == 7.80

        # 19:30 -> Peak (18:00 - 22:00 @ ₹10.50)
        dt_peak = datetime(2026, 11, 4, 19, 30, 0, tzinfo=timezone.utc)
        slot, rate = cost_engine.get_tod_rate(dt_peak)
        assert slot == "peak"
        assert rate == 10.50

    def test_cost_calculation_math(self, cost_engine: CostAndCarbonEngine) -> None:
        """Verify that energy cost includes FPPCA fuel surcharge and electricity duty."""
        # Off-peak 100 kWh: (5.20 + 0.65) * 1.093 * 100 = 5.85 * 1.093 * 100 = 639.405 -> 639.41
        dt_offpeak = datetime(2026, 11, 4, 2, 0, 0, tzinfo=timezone.utc)
        cost = cost_engine.calculate_cost(100.0, dt_offpeak)
        assert abs(cost - 639.41) < 0.50

        # Peak 100 kWh: (10.50 + 0.65) * 1.093 * 100 = 11.15 * 1.093 * 100 = 1218.695 -> 1218.70
        dt_peak = datetime(2026, 11, 4, 19, 0, 0, tzinfo=timezone.utc)
        cost_peak = cost_engine.calculate_cost(100.0, dt_peak)
        assert abs(cost_peak - 1218.70) < 0.50
        assert cost_peak > cost

    def test_carbon_emission_factor(self, cost_engine: CostAndCarbonEngine) -> None:
        """Verify carbon footprint conversion follows CEA 0.82 kg CO2 / kWh factor."""
        # 1000 kWh -> 820.0 kg CO2
        co2 = cost_engine.calculate_co2(1000.0)
        assert co2 == 820.0
        assert cost_engine.calculate_co2(0.0) == 0.0

    def test_demand_penalty_calculation(self, cost_engine: CostAndCarbonEngine) -> None:
        """Verify demand charge penalty applies when exceeding contract demand (280 kVA)."""
        # Within contract demand -> 0 penalty
        assert cost_engine.calculate_demand_penalty(250.0) == 0.0
        assert cost_engine.calculate_demand_penalty(280.0) == 0.0

        # Excess 20 kVA (300 kVA total): 20 kVA * 450 Rs/kVA * 1.5 multiplier = 13,500 Rs
        penalty = cost_engine.calculate_demand_penalty(300.0)
        assert penalty == 13500.0

