"""Pydantic schemas for FastAPI request validation and API responses."""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "healthy"
    database: str
    timestamp: str


class MachineInfo(BaseModel):
    machine_id: str
    name: str
    category: str
    rated_power_kw: float
    nominal_voltage_v: float
    nominal_power_factor: float


class LiveReading(BaseModel):
    machine_id: str
    timestamp: str
    state: str
    voltage: float
    current: float
    power_kw: float
    power_factor: float
    energy_kwh: float


class HistoryPoint(BaseModel):
    time: str
    machine_id: str
    power_kw: float
    current: Optional[float] = None
    voltage: Optional[float] = None
    power_factor: Optional[float] = None
    energy_kwh: Optional[float] = None


class HistoryResponse(BaseModel):
    machine_id: str
    resolution: str
    count: int
    data: List[HistoryPoint]


class WasteEventResponse(BaseModel):
    id: int
    event_type: str
    machine_id: str
    start_time: str
    end_time: str
    kwh_wasted: float
    cost_inr: float
    severity: str
    description: str


class PaginatedWasteEvents(BaseModel):
    total: int
    limit: int
    offset: int
    events: List[WasteEventResponse]


class ForecastPoint(BaseModel):
    target_time: str
    predicted_kw: float
    lower_bound_kw: float
    upper_bound_kw: float
    model_name: str


class ForecastResponse(BaseModel):
    machine_id: str
    granularity: str
    forecast_time: str
    predictions: List[ForecastPoint]


class RecommendationResponse(BaseModel):
    id: int
    machine_id: str
    action: str
    estimated_monthly_kwh_saved: float
    estimated_monthly_inr_saved: float
    co2_avoided_kg: float
    priority_rank: int
    status: str


class PlantSummaryResponse(BaseModel):
    date: str
    todays_kwh: float
    todays_cost_inr: float
    todays_co2_kg: float
    active_machines_count: int
    current_plant_kw: float
    monthly_savings_potential_inr: float
    monthly_savings_potential_kwh: float
    monthly_co2_reduction_kg: float

