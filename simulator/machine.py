"""Simulated industrial machine entity with electrical calculations and noise."""

from datetime import datetime, timezone
import logging
import math
import random
from typing import Optional

from simulator.models import MachineConfig, MachineState, MachineTelemetry

logger = logging.getLogger(__name__)


class SimulatedMachine:
    """Represents a virtual industrial machine with dynamic electrical telemetry."""

    def __init__(
        self,
        config: MachineConfig,
        noise_std_pct: float = 0.02,
        voltage_variation_std_pct: float = 0.015,
        initial_energy_kwh: float = 0.0,
    ) -> None:
        """Initialize SimulatedMachine.

        Args:
            config: Machine specifications and load profiles.
            noise_std_pct: Relative standard deviation of Gaussian noise on power.
            voltage_variation_std_pct: Relative standard deviation of voltage fluctuation.
            initial_energy_kwh: Initial value on cumulative energy meter.
        """
        self.config = config
        self.noise_std_pct = noise_std_pct
        self.voltage_variation_std_pct = voltage_variation_std_pct
        self.cumulative_energy_kwh = float(initial_energy_kwh)
        self.current_state = MachineState.OFF
        self.last_update_dt: Optional[datetime] = None

    def calculate_voltage(self) -> float:
        """Generate instantaneous RMS line voltage with grid fluctuation."""
        nom_v = self.config.nominal_voltage_v
        std_v = nom_v * self.voltage_variation_std_pct
        # Gaussian perturbation around nominal voltage
        v = random.gauss(nom_v, std_v)
        return max(350.0 if nom_v >= 400.0 else 200.0, min(v, nom_v * 1.10))

    def step(
        self,
        target_state: MachineState,
        dt: datetime,
        elapsed_seconds: float,
        forced_power_kw: Optional[float] = None,
    ) -> MachineTelemetry:
        """Advance machine simulation by elapsed_seconds and produce telemetry.

        Args:
            target_state: Target MachineState determined by schedule and faults.
            dt: Current simulation datetime timestamp.
            elapsed_seconds: Simulated seconds elapsed since previous step.
            forced_power_kw: Optional overridden power value (from faults).

        Returns:
            Validated MachineTelemetry data object.
        """
        self.current_state = target_state
        state_key = target_state.value
        profile = self.config.states.get(state_key)

        # Baseline active power calculation
        if forced_power_kw is not None:
            base_power = forced_power_kw
            power_factor = profile.power_factor if profile else self.config.nominal_power_factor
        elif target_state == MachineState.OFF or profile is None:
            base_power = 0.0
            power_factor = 0.0
        else:
            # Pick uniform draw within state range
            load_fraction = random.uniform(profile.load_pct_min, profile.load_pct_max)
            base_power = self.config.rated_power_kw * load_fraction
            power_factor = profile.power_factor

        # Add Gaussian process noise to active power
        if base_power > 0.0:
            noise_std = self.config.rated_power_kw * self.noise_std_pct
            active_power_kw = max(0.05, random.gauss(base_power, noise_std))
        else:
            active_power_kw = 0.0

        # Calculate voltage
        voltage_v = self.calculate_voltage() if active_power_kw > 0.0 else self.config.nominal_voltage_v

        # Ensure power factor is bounded between 0.1 and 1.0 when drawing active power
        if active_power_kw > 0.0:
            # Slight random jitter on power factor (+/- 0.01)
            pf_jitter = random.gauss(0.0, 0.005)
            effective_pf = max(0.40, min(0.99, power_factor + pf_jitter))
        else:
            effective_pf = 0.0

        # Electrical Current calculation:
        # P (kW) * 1000 = sqrt(3) * V_L * I_L * PF for 3-phase
        # P (kW) * 1000 = V * I * PF for 1-phase
        if active_power_kw > 0.0 and effective_pf > 0.0:
            if self.config.phase_count == 3:
                current_a = (active_power_kw * 1000.0) / (math.sqrt(3.0) * voltage_v * effective_pf)
            else:
                current_a = (active_power_kw * 1000.0) / (voltage_v * effective_pf)
        else:
            current_a = 0.0

        # Update cumulative kWh meter reading
        # Energy (kWh) = Power (kW) * time (hours)
        delta_kwh = active_power_kw * (elapsed_seconds / 3600.0)
        self.cumulative_energy_kwh += delta_kwh
        self.last_update_dt = dt

        # Form ISO 8601 timestamp string
        ts_str = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return MachineTelemetry(
            machine_id=self.config.machine_id,
            timestamp=ts_str,
            state=self.current_state.value,
            voltage=round(voltage_v, 2),
            current=round(current_a, 2),
            power_kw=round(active_power_kw, 3),
            power_factor=round(effective_pf, 3),
            energy_kwh=round(self.cumulative_energy_kwh, 4),
        )

