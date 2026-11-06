"""Pydantic data models for machine telemetry and configurations."""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class MachineState(str, Enum):
    """Enumeration of valid operational machine states."""
    OFF = "OFF"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FAULT = "FAULT"


class MachineTelemetry(BaseModel):
    """Validated telemetry payload emitted by a machine sensor node."""

    machine_id: str = Field(..., description="Unique machine identifier string")
    timestamp: str = Field(..., description="ISO 8601 formatted UTC timestamp")
    state: str = Field(..., description="Current operating state (OFF, IDLE, RUNNING, FAULT)")
    voltage: float = Field(..., ge=0.0, description="Measured line-to-line RMS voltage in Volts")
    current: float = Field(..., ge=0.0, description="Calculated three-phase line current in Amperes")
    power_kw: float = Field(..., ge=0.0, description="Active electric power consumption in Kilowatts")
    power_factor: float = Field(..., ge=0.0, le=1.0, description="Measured electrical power factor (cos phi)")
    energy_kwh: float = Field(..., ge=0.0, description="Cumulative electrical energy meter reading in kWh")

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        """Ensure state conforms to recognized MachineState names."""
        v_upper = v.upper()
        if v_upper not in MachineState._value2member_map_:
            raise ValueError(f"Invalid machine state '{v}'. Must be one of {[s.value for s in MachineState]}")
        return v_upper


class StateProfile(BaseModel):
    """Operating profile for a given machine state."""
    load_pct_min: float = 0.0
    load_pct_max: float = 0.0
    power_factor: float = 0.0
    description: Optional[str] = None


class MachineConfig(BaseModel):
    """Full machine specification parsed from config/machines.yaml."""
    machine_id: str
    name: str
    category: str
    rated_power_kw: float
    nominal_voltage_v: float = 415.0
    phase_count: int = 3
    nominal_power_factor: float = 0.85
    states: Dict[str, StateProfile]
    faults: Dict[str, Dict] = Field(default_factory=dict)

