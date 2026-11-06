-- =============================================================================
-- Smart Industrial Energy Monitoring System
-- TimescaleDB Schema Definition, Hypertables, and Continuous Aggregates
-- =============================================================================

-- Enable TimescaleDB extension if available
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- -----------------------------------------------------------------------------
-- 1. Raw Telemetry Hypertable
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telemetry (
    time TIMESTAMPTZ NOT NULL,
    machine_id VARCHAR(64) NOT NULL,
    state VARCHAR(16) NOT NULL,
    voltage DOUBLE PRECISION NOT NULL,
    current DOUBLE PRECISION NOT NULL,
    power_kw DOUBLE PRECISION NOT NULL,
    power_factor DOUBLE PRECISION NOT NULL,
    energy_kwh DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (time, machine_id)
);

-- Convert to TimescaleDB hypertable partitioned by time (1-day chunk interval)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('telemetry', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_telemetry_machine_time ON telemetry (machine_id, time DESC);

-- -----------------------------------------------------------------------------
-- 2. Continuous Aggregates (1-Minute, 15-Minute, Hourly, Daily Rollups)
-- -----------------------------------------------------------------------------

-- 1-Minute Continuous Aggregate
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        EXECUTE '
        CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(''1 minute'', time) AS bucket,
            machine_id,
            AVG(power_kw) AS avg_power_kw,
            MAX(power_kw) AS max_power_kw,
            MIN(power_kw) AS min_power_kw,
            AVG(current) AS avg_current,
            AVG(voltage) AS avg_voltage,
            AVG(power_factor) AS avg_power_factor,
            MAX(energy_kwh) - MIN(energy_kwh) AS delta_kwh
        FROM telemetry
        GROUP BY bucket, machine_id
        WITH NO DATA;';
    END IF;
END $$;

-- 15-Minute Continuous Aggregate (Used for Plant Contract Demand & Peak Analysis)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        EXECUTE '
        CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_15m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(''15 minutes'', time) AS bucket,
            machine_id,
            AVG(power_kw) AS avg_power_kw,
            MAX(power_kw) AS max_power_kw,
            AVG(power_factor) AS avg_power_factor,
            MAX(energy_kwh) - MIN(energy_kwh) AS delta_kwh
        FROM telemetry
        GROUP BY bucket, machine_id
        WITH NO DATA;';
    END IF;
END $$;

-- Hourly Continuous Aggregate
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        EXECUTE '
        CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(''1 hour'', time) AS bucket,
            machine_id,
            AVG(power_kw) AS avg_power_kw,
            MAX(power_kw) AS max_power_kw,
            AVG(power_factor) AS avg_power_factor,
            MAX(energy_kwh) - MIN(energy_kwh) AS delta_kwh
        FROM telemetry
        GROUP BY bucket, machine_id
        WITH NO DATA;';
    END IF;
END $$;

-- Daily Continuous Aggregate
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        EXECUTE '
        CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_daily
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(''1 day'', time) AS bucket,
            machine_id,
            AVG(power_kw) AS avg_power_kw,
            MAX(power_kw) AS max_power_kw,
            MAX(energy_kwh) - MIN(energy_kwh) AS delta_kwh
        FROM telemetry
        GROUP BY bucket, machine_id
        WITH NO DATA;';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 3. Wastage Events Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS waste_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(32) NOT NULL, -- 'IDLE_WASTE', 'ANOMALY', 'PEAK_DEMAND'
    machine_id VARCHAR(64) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    kwh_wasted DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    cost_inr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    severity VARCHAR(16) NOT NULL DEFAULT 'MEDIUM', -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_waste_events_machine_time ON waste_events (machine_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_waste_events_type ON waste_events (event_type);

-- -----------------------------------------------------------------------------
-- 4. Demand Forecasts Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
    id SERIAL PRIMARY KEY,
    forecast_time TIMESTAMPTZ NOT NULL, -- When the forecast was computed
    target_time TIMESTAMPTZ NOT NULL,   -- The future timestamp being predicted
    machine_id VARCHAR(64) NOT NULL,    -- Specific machine or 'PLANT'
    granularity VARCHAR(16) NOT NULL,   -- 'HOURLY' or 'DAILY'
    predicted_kw DOUBLE PRECISION NOT NULL,
    lower_bound_kw DOUBLE PRECISION NOT NULL,
    upper_bound_kw DOUBLE PRECISION NOT NULL,
    model_name VARCHAR(32) NOT NULL,    -- 'LightGBM' or 'SeasonalNaive'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forecasts_target ON forecasts (machine_id, target_time);

-- -----------------------------------------------------------------------------
-- 5. Forecast Model Comparison Metrics Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecast_metrics (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(32) NOT NULL,
    granularity VARCHAR(16) NOT NULL,
    mae DOUBLE PRECISION NOT NULL,
    rmse DOUBLE PRECISION NOT NULL,
    mape DOUBLE PRECISION NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 6. Actionable Energy Recommendations Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recommendations (
    id SERIAL PRIMARY KEY,
    machine_id VARCHAR(64) NOT NULL,
    action TEXT NOT NULL,
    estimated_monthly_kwh_saved DOUBLE PRECISION NOT NULL,
    estimated_monthly_inr_saved DOUBLE PRECISION NOT NULL,
    co2_avoided_kg DOUBLE PRECISION NOT NULL,
    priority_rank INTEGER NOT NULL, -- 1 = Highest, 2 = Medium, 3 = Lower
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recommendations_rank ON recommendations (priority_rank);

