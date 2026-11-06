"""Fault injection models for simulating industrial equipment anomalies."""

from datetime import datetime
import logging
from typing import Dict, Optional, Tuple

from simulator.models import MachineState

logger = logging.getLogger(__name__)


class FaultManager:
    """Manages active and scheduled fault injections across simulated machines."""

    def __init__(self, enable_faults: bool = True) -> None:
        """Initialize FaultManager.

        Args:
            enable_faults: Global toggle for fault injection behavior.
        """
        self.enable_faults = enable_faults
        # Active fault registry: machine_id -> fault_name
        self.active_faults: Dict[str, str] = {}
        # Degradation tracking: machine_id -> drift accumulator
        self.degradation_accumulators: Dict[str, float] = {
            "conveyor": 0.0,
            "air_compressor": 0.0,
        }

    def activate_fault(self, machine_id: str, fault_name: str) -> None:
        """Manually trigger or configure a fault for a specific machine."""
        self.active_faults[machine_id] = fault_name
        logger.info(f"Activated fault '{fault_name}' on machine '{machine_id}'")

    def clear_fault(self, machine_id: str) -> None:
        """Clear active fault from a machine."""
        if machine_id in self.active_faults:
            removed = self.active_faults.pop(machine_id)
            logger.info(f"Cleared fault '{removed}' on machine '{machine_id}'")

    def update_degradation(self, machine_id: str, elapsed_sim_hours: float) -> None:
        """Advance physical degradation state (e.g., motor bearing wear)."""
        if not self.enable_faults:
            return

        if machine_id == "conveyor" and self.active_faults.get("conveyor") == "motor_degradation":
            # 0.15% power/current increase per simulated operating hour
            self.degradation_accumulators["conveyor"] += 0.0015 * elapsed_sim_hours

    def apply_fault_effects(
        self,
        machine_id: str,
        nominal_state: MachineState,
        nominal_power: float,
        dt: datetime,
    ) -> Tuple[MachineState, float, Optional[str]]:
        """Apply active fault modifications to nominal machine state and power draw.

        Args:
            machine_id: Target machine identifier.
            nominal_state: Scheduled state before fault injection.
            nominal_power: Base calculated power in kW.
            dt: Current simulation datetime.

        Returns:
            Tuple of (effective_state, adjusted_power_kw, fault_applied_description)
        """
        if not self.enable_faults:
            return nominal_state, nominal_power, None

        fault = self.active_faults.get(machine_id)
        if not fault:
            return nominal_state, nominal_power, None

        effective_state = nominal_state
        adjusted_power = nominal_power
        desc: Optional[str] = None

        # 1. Compressor Air Leak: Elevated idle baseline draw (+25%)
        if machine_id == "air_compressor" and fault == "air_leak":
            if effective_state == MachineState.IDLE:
                adjusted_power = nominal_power * 1.30
                desc = "Air leak: elevated idle draw"
            elif effective_state == MachineState.OFF:
                # Slight leak pressure loss causes occasional short compressor cycle
                effective_state = MachineState.IDLE
                adjusted_power = nominal_power * 1.25
                desc = "Air leak: leak cycles unloaded compressor while plant off"

        # 2. Conveyor Motor Degradation: Continuous current/power creep
        elif machine_id == "conveyor" and fault == "motor_degradation":
            drift = self.degradation_accumulators.get("conveyor", 0.0)
            # Power increases proportionally with bearing friction
            adjusted_power = nominal_power * (1.0 + drift)
            if nominal_state != MachineState.OFF:
                desc = f"Motor degradation: bearing friction adds {drift*100:.1f}% draw"

        # 3. Machines Left Idle Overnight (Unattended Waste)
        elif fault == "unattended_overnight":
            # If nominal schedule dictates OFF, fault keeps it idling
            if nominal_state == MachineState.OFF:
                effective_state = MachineState.IDLE
                # Typical idle power depending on machine
                desc = "Unattended overnight: machine left idling in off-shift"

        # 4. Sudden Peak Spike
        elif fault == "peak_spike":
            if effective_state in (MachineState.RUNNING, MachineState.IDLE):
                effective_state = MachineState.FAULT
                adjusted_power = nominal_power * 1.55
                desc = "Transient peak spike: load surge"

        # 5. Conveyor running during breaks
        elif machine_id == "conveyor" and fault == "running_during_breaks":
            if nominal_state == MachineState.IDLE:
                effective_state = MachineState.RUNNING
                desc = "Conveyor running empty during worker break"

        # 6. Lighting left on over weekend
        elif machine_id == "lighting" and fault == "lights_left_on_weekend":
            if dt.weekday() == 6:  # Sunday
                effective_state = MachineState.RUNNING
                desc = "High-bay lighting left fully powered over Sunday shutdown"

        return effective_state, adjusted_power, desc

