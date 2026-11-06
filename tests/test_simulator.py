"""Unit tests for the industrial machine telemetry simulator."""

from datetime import datetime, timezone
import math
from pathlib import Path
import pytest

from simulator.config_loader import load_machines_config, load_simulator_config
from simulator.faults import FaultManager
from simulator.machine import SimulatedMachine
from simulator.models import MachineConfig, MachineState, MachineTelemetry
from simulator.shift_manager import ShiftManager


@pytest.fixture
def config_dir() -> Path:
    """Fixture pointing to the root config directory."""
    return Path(__file__).parent.parent / "config"


@pytest.fixture
def machines_config(config_dir: Path) -> dict:
    """Fixture providing loaded machine configurations."""
    return load_machines_config(config_dir)


@pytest.fixture
def simulator_config(config_dir: Path) -> dict:
    """Fixture providing loaded simulator configurations."""
    return load_simulator_config(config_dir)


class TestConfigLoader:
    """Test suite for verifying configuration files and loader parsing."""

    def test_machines_yaml_contains_all_six_machines(self, machines_config: dict) -> None:
        """Verify that all 6 required industrial machines are configured."""
        expected_machines = {
            "air_compressor",
            "cnc_machine",
            "induction_furnace",
            "conveyor",
            "hvac",
            "lighting",
        }
        assert set(machines_config.keys()) == expected_machines

    def test_machine_attributes_are_valid(self, machines_config: dict) -> None:
        """Verify rated power, nominal voltages, and states for each machine."""
        for mid, mcfg in machines_config.items():
            assert mcfg.rated_power_kw > 0.0
            assert mcfg.nominal_voltage_v in (230.0, 415.0)
            assert set(mcfg.states.keys()).issuperset({"OFF", "IDLE", "RUNNING"})

            # Compressor specific idle fraction rule from brief (25-35%)
            if mid == "air_compressor":
                idle_profile = mcfg.states["IDLE"]
                assert idle_profile.load_pct_min >= 0.20
                assert idle_profile.load_pct_max <= 0.40


class TestShiftManager:
    """Test suite for factory shifts and breaks scheduling."""

    def test_weekday_morning_shift(self, simulator_config: dict) -> None:
        """Verify Morning Shift active at 08:00 on a Wednesday."""
        mgr = ShiftManager(simulator_config)
        wednesday_morning = datetime(2026, 11, 4, 8, 0, 0, tzinfo=timezone.utc)  # Wednesday
        shift = mgr.get_current_shift(wednesday_morning)
        assert shift is not None
        shift_key, shift_info = shift
        assert shift_key == "shift_1"

    def test_lunch_break_detection(self, simulator_config: dict) -> None:
        """Verify lunch break is recognized at 12:45."""
        mgr = ShiftManager(simulator_config)
        lunch_time = datetime(2026, 11, 4, 12, 45, 0, tzinfo=timezone.utc)
        brk = mgr.get_current_break(lunch_time)
        assert brk is not None
        assert "Lunch" in brk["name"]

    def test_sunday_plant_shutdown(self, simulator_config: dict) -> None:
        """Verify plant shutdown on Sunday (no shift active)."""
        mgr = ShiftManager(simulator_config)
        sunday_midday = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)  # Sunday
        shift = mgr.get_current_shift(sunday_midday)
        assert shift is None

        # Conveyor should be OFF on Sunday
        state = mgr.determine_nominal_state("conveyor", sunday_midday)
        assert state == MachineState.OFF

        # Lighting should be IDLE path lighting on Sunday
        lighting_state = mgr.determine_nominal_state("lighting", sunday_midday)
        assert lighting_state == MachineState.IDLE


class TestFaultManager:
    """Test suite for fault injection behavior."""

    def test_compressor_air_leak_fault(self) -> None:
        """Verify compressor air leak elevates idle draw."""
        mgr = FaultManager(enable_faults=True)
        mgr.activate_fault("air_compressor", "air_leak")

        dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)
        state, power, desc = mgr.apply_fault_effects(
            "air_compressor", MachineState.IDLE, 10.0, dt
        )
        assert state == MachineState.IDLE
        assert power > 10.0  # Elevated power draw
        assert desc is not None
        assert "Air leak" in desc

    def test_motor_degradation_drift(self) -> None:
        """Verify conveyor motor degradation increases current and power draw over time."""
        mgr = FaultManager(enable_faults=True)
        mgr.activate_fault("conveyor", "motor_degradation")

        dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)
        # Advance 100 operating hours
        mgr.update_degradation("conveyor", 100.0)

        state, power, desc = mgr.apply_fault_effects(
            "conveyor", MachineState.RUNNING, 10.0, dt
        )
        assert power > 10.0
        assert "Motor degradation" in desc


class TestSimulatedMachine:
    """Test suite for machine electrical calculations, noise, and telemetry generation."""

    def test_telemetry_schema_and_calculations(self, machines_config: dict) -> None:
        """Verify electrical formulas and Pydantic validation."""
        conveyor_cfg = machines_config["conveyor"]
        machine = SimulatedMachine(conveyor_cfg, initial_energy_kwh=50.0)

        dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)
        telemetry = machine.step(
            target_state=MachineState.RUNNING,
            dt=dt,
            elapsed_seconds=2.0,
        )

        assert isinstance(telemetry, MachineTelemetry)
        assert telemetry.machine_id == "conveyor"
        assert telemetry.state == "RUNNING"
        assert telemetry.power_kw > 0.0
        assert telemetry.voltage > 380.0
        assert 0.50 <= telemetry.power_factor <= 1.0

        # Verify current calculation follows 3-phase formula: P*1000 / (sqrt(3)*V*PF)
        expected_current = (telemetry.power_kw * 1000.0) / (
            math.sqrt(3.0) * telemetry.voltage * telemetry.power_factor
        )
        assert abs(telemetry.current - expected_current) < 0.5

        # Verify cumulative energy increased
        assert telemetry.energy_kwh > 50.0
        expected_energy = 50.0 + (telemetry.power_kw * 2.0 / 3600.0)
        assert abs(telemetry.energy_kwh - expected_energy) < 0.001

    def test_off_state_draws_zero_power(self, machines_config: dict) -> None:
        """Verify machine in OFF state draws 0 kW and 0 A."""
        cnc_cfg = machines_config["cnc_machine"]
        machine = SimulatedMachine(cnc_cfg, initial_energy_kwh=10.0)

        dt = datetime(2026, 11, 4, 23, 0, 0, tzinfo=timezone.utc)
        telemetry = machine.step(
            target_state=MachineState.OFF,
            dt=dt,
            elapsed_seconds=2.0,
        )

        assert telemetry.state == "OFF"
        assert telemetry.power_kw == 0.0
        assert telemetry.current == 0.0
        assert telemetry.energy_kwh == 10.0

