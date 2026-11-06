"""Shift, schedule, and break period management for the virtual factory."""

from datetime import datetime, time
import logging
from typing import Any, Dict, List, Optional, Tuple

from simulator.models import MachineState

logger = logging.getLogger(__name__)


class ShiftManager:
    """Evaluates factory operating schedules, active shifts, and break intervals."""

    def __init__(self, simulator_config: Dict[str, Any]) -> None:
        """Initialize ShiftManager with parsed simulator.yaml configuration.

        Args:
            simulator_config: Parsed contents of simulator.yaml.
        """
        self.shifts = simulator_config.get("shifts", {})
        self.breaks = simulator_config.get("breaks", [])
        self.weekend_schedule = simulator_config.get("weekend_schedule", {})

    @staticmethod
    def _parse_time(time_str: str) -> time:
        """Parse HH:MM string into datetime.time object."""
        hour, minute = map(int, time_str.split(":"))
        return time(hour, minute)

    def is_in_time_range(self, t: time, start: time, end: time) -> bool:
        """Check whether time t is between start and end (handling overnight rollover)."""
        if start <= end:
            return start <= t < end
        # Overnight window (e.g. 22:00 to 06:00)
        return t >= start or t < end

    def get_current_shift(self, dt: datetime) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Determine active shift for a given datetime timestamp.

        Args:
            dt: Simulation timestamp to evaluate.

        Returns:
            Tuple of (shift_key, shift_dict) or None if no shift is active (e.g., Sunday).
        """
        weekday = dt.weekday()  # Monday is 0, Sunday is 6
        current_time = dt.time()

        # Sunday check
        if weekday == 6:
            allowed_shifts = self.weekend_schedule.get("sunday", {}).get("working_shifts", [])
            if not allowed_shifts:
                return None
        elif weekday == 5:
            # Saturday check
            allowed_shifts = self.weekend_schedule.get("saturday", {}).get(
                "working_shifts", ["shift_1", "shift_2"]
            )
        else:
            allowed_shifts = list(self.shifts.keys())

        for shift_key, shift_info in self.shifts.items():
            if shift_key not in allowed_shifts:
                continue
            start_t = self._parse_time(shift_info["start_time"])
            end_t = self._parse_time(shift_info["end_time"])

            if self.is_in_time_range(current_time, start_t, end_t):
                return shift_key, shift_info

        return None

    def get_current_break(self, dt: datetime) -> Optional[Dict[str, Any]]:
        """Check if timestamp falls into a scheduled worker meal or tea break."""
        current_time = dt.time()
        for brk in self.breaks:
            start_t = self._parse_time(brk["start_time"])
            end_t = self._parse_time(brk["end_time"])
            if self.is_in_time_range(current_time, start_t, end_t):
                return brk
        return None

    def determine_nominal_state(self, machine_id: str, dt: datetime) -> MachineState:
        """Determine expected nominal operating state for a machine at timestamp dt.

        Rules:
        - If Sunday/off-shift: machines are OFF, except lighting (IDLE path lighting) and HVAC (OFF).
        - If break (e.g. Lunch):
          - Conveyor, CNC should ideally be IDLE/OFF.
          - Furnace stays in IDLE (holding molten bath).
          - Compressor remains IDLE/unloaded.
          - HVAC continues RUNNING.
          - Lighting continues RUNNING.
        - During normal working shift:
          - Scheduled machines are RUNNING.
        """
        shift = self.get_current_shift(dt)
        brk = self.get_current_break(dt)

        # Plant shutdown / Sunday / no active shift
        if shift is None:
            if machine_id == "lighting":
                return MachineState.IDLE  # Night/security path lighting
            return MachineState.OFF

        shift_key, shift_info = shift
        active_machines = shift_info.get("active_machines", [])

        # Machine not scheduled for this shift
        if machine_id not in active_machines:
            return MachineState.OFF

        # During break intervals
        if brk is not None:
            if machine_id in ("conveyor", "cnc_machine"):
                return MachineState.IDLE  # Standby during meal break
            elif machine_id == "induction_furnace":
                return MachineState.IDLE  # Holding temperature
            elif machine_id == "air_compressor":
                return MachineState.IDLE  # Low demand idle
            else:
                return MachineState.RUNNING

        # Normal production shift
        return MachineState.RUNNING

