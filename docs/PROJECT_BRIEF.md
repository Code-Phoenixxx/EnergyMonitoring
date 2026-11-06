# Smart Industrial Energy Monitoring System

Industry 4.0 course project. Monitor machine-level electricity consumption, identify energy wastage, and forecast energy demand. Everything runs locally with one command (`docker compose up`), using simulated data and no hardware.

## Goal
A virtual factory with 6 machines streams power readings over MQTT into a time-series database. Analytics modules detect idle waste, anomalies, and demand peaks, forecast future demand, and convert findings into rupee and CO2 savings. A dashboard shows everything live.

## Tech stack (do not change)
- Python 3.11
- MQTT: Eclipse Mosquitto, paho-mqtt
- Database: TimescaleDB
- Backend: FastAPI, SQLAlchemy, Pydantic
- ML: scikit-learn (Isolation Forest), LightGBM, pandas, numpy
- Dashboard: Streamlit with Plotly
- Deployment: Docker Compose (services: mosquitto, timescaledb, simulator, ingestion, api, analytics-worker, dashboard)
- Testing: pytest

## Components

### 1. Machine simulator
- 6 machines: air compressor, CNC machine, induction furnace, conveyor, HVAC, lighting.
- Each has rated power (kW), states (OFF, IDLE, RUNNING, FAULT), a load profile per state, Gaussian noise, and a shift schedule (3 shifts, weekday/weekend variation, lunch breaks).
- Idle draw is a realistic fraction of rated power (e.g. compressor idles at about 25-35%).
- Inject faults: compressor air leak (higher baseline), motor degradation (current rises gradually), machines left idle overnight, sudden peak spikes.
- Publish JSON every 2 seconds per machine to `factory/{machine_id}/telemetry` with: machine_id, timestamp, state, voltage, current, power_kw, power_factor, energy_kwh.
- `--speedup` flag to simulate days quickly, and a backfill script that generates 60 days of history.

### 2. Ingestion service
- Subscribe to `factory/+/telemetry`, validate with Pydantic, batch-insert into a TimescaleDB hypertable.
- Handle reconnects and malformed messages without crashing.
- Continuous aggregates for 1-minute, 15-minute, hourly, and daily rollups.

### 3. Wastage detection (core feature)
- Idle waste: flag machines in IDLE/OFF state drawing more than a configurable percentage of rated power. Compute wasted kWh and cost.
- Anomaly detection: one Isolation Forest per machine, trained on normal-operation features (power, current, power factor, rolling mean/std, hour of day). Score the live stream and give a severity score.
- Peak demand: rolling 15-minute average kW, flag breaches of a configurable plant limit.
- Write every finding to a `waste_events` table: event_type, machine_id, start, end, kwh_wasted, cost_inr, severity, description.

### 4. Forecasting
- Hourly demand for the next 24 hours and daily demand for the next 7 days, per machine and plant-wide.
- Features: hour, day of week, shift, lags (1h, 24h, 168h), rolling means, simulated temperature.
- Models: seasonal-naive baseline and LightGBM. Time-based train/test split only. Report MAE, RMSE, MAPE for both as a comparison table.
- Store forecasts and metrics in the database. Retrain on a schedule.

### 5. Cost and carbon engine
- Time-of-day tariff in YAML: peak, normal, off-peak Rs/kWh, plus a Rs/kVA maximum demand charge. Use realistic Indian industrial values and comment where to change them.
- CO2 from kWh using a configurable grid emission factor (default 0.82 kg CO2/kWh, CEA India).

### 6. Recommendation engine (rule-based)
- Generate actions from waste events and forecasts, e.g. switch off the conveyor during breaks, fix the compressor leak, shift furnace preheat to off-peak hours.
- Each recommendation includes: machine, action, estimated monthly kWh saved, Rs saved, CO2 avoided, priority rank.

### 7. FastAPI backend
Endpoints: `GET /machines`, `/machines/{id}/live`, `/machines/{id}/history?from&to&resolution`, `/waste-events`, `/forecast`, `/recommendations`, `/summary` (today's kWh, cost, CO2, savings potential), `/health`. OpenAPI docs and pagination.

### 8. Streamlit dashboard (4 pages)
- Live Overview: power per machine (gauges and live line chart), plant total kW, status badges.
- Wastage: events table sorted by cost, breakdown by type, idle-hours heatmap by machine and hour.
- Forecast: actual vs forecast with confidence band, model comparison table.
- Savings: ranked recommendations and total monthly savings in Rs and CO2.

### 9. Before/after experiment
Simulate a baseline week, apply the recommendations in the simulator, simulate another week, and output the measured kWh and Rs reduction as a chart and CSV. This is the headline result.

## Non-functional requirements
- Folders: /simulator, /ingestion, /api, /analytics, /dashboard, /config, /tests, /scripts, /docs
- All settings (machine specs, thresholds, tariffs, emission factor) in config/*.yaml. No hardcoded values.
- Type hints, docstrings, logging. No unused code.
- `.env.example`, a Makefile (`make up`, `make backfill`, `make train`, `make test`), pinned requirements per service.
- Unit tests for idle detection, peak calculation, cost engine, and API endpoints.

## Final deliverable
README with a Mermaid architecture diagram, setup steps, a screenshot checklist, and a "How this maps to Industry 4.0" section (IIoT, big data, AI/ML, digital twin, sustainability).

