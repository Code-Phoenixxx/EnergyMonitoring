"""SQLAlchemy declarative models for TimescaleDB and analytics storage."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class TelemetryRecord(Base):
    """Raw high-frequency telemetry observation stored in TimescaleDB hypertable."""

    __tablename__ = "telemetry"

    time = Column(DateTime(timezone=True), nullable=False)
    machine_id = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False)
    voltage = Column(Float, nullable=False)
    current = Column(Float, nullable=False)
    power_kw = Column(Float, nullable=False)
    power_factor = Column(Float, nullable=False)
    energy_kwh = Column(Float, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("time", "machine_id"),
    )


class WasteEventRecord(Base):
    """Energy wastage, idle loss, anomaly, or peak demand breach incident."""

    __tablename__ = "waste_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(32), nullable=False)  # 'IDLE_WASTE', 'ANOMALY', 'PEAK_DEMAND'
    machine_id = Column(String(64), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    kwh_wasted = Column(Float, nullable=False, default=0.0)
    cost_inr = Column(Float, nullable=False, default=0.0)
    severity = Column(String(16), nullable=False, default="MEDIUM")  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class ForecastRecord(Base):
    """Model predictions for machine-level and plant-wide power demand."""

    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    forecast_time = Column(DateTime(timezone=True), nullable=False)
    target_time = Column(DateTime(timezone=True), nullable=False)
    machine_id = Column(String(64), nullable=False)
    granularity = Column(String(16), nullable=False)  # 'HOURLY', 'DAILY'
    predicted_kw = Column(Float, nullable=False)
    lower_bound_kw = Column(Float, nullable=False)
    upper_bound_kw = Column(Float, nullable=False)
    model_name = Column(String(32), nullable=False)  # 'LightGBM', 'SeasonalNaive'
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class ForecastMetricRecord(Base):
    """Evaluation metrics comparing forecasting models."""

    __tablename__ = "forecast_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(32), nullable=False)
    granularity = Column(String(16), nullable=False)
    mae = Column(Float, nullable=False)
    rmse = Column(Float, nullable=False)
    mape = Column(Float, nullable=False)
    sample_count = Column(Integer, nullable=False, default=0)
    evaluated_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class RecommendationRecord(Base):
    """Synthesized actionable recommendations to reduce energy waste and cost."""

    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(String(64), nullable=False)
    action = Column(Text, nullable=False)
    estimated_monthly_kwh_saved = Column(Float, nullable=False)
    estimated_monthly_inr_saved = Column(Float, nullable=False)
    co2_avoided_kg = Column(Float, nullable=False)
    priority_rank = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

