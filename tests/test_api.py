"""Unit tests for FastAPI REST API endpoints using real database session."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from api.main import app
from database.connection import SessionLocal
from database.models import RecommendationRecord, TelemetryRecord


@pytest.fixture
def client():
    """TestClient fixture for FastAPI endpoints."""
    return TestClient(app)


class TestApiEndpoints:
    """Test suite for REST endpoints, schema validation, and error codes."""

    def test_health_endpoint(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert "timestamp" in data

    def test_machines_list(self, client: TestClient):
        response = client.get("/machines")
        assert response.status_code == 200
        machines = response.json()
        assert len(machines) == 6
        machine_ids = {m["machine_id"] for m in machines}
        assert "air_compressor" in machine_ids
        assert "induction_furnace" in machine_ids

    def test_machine_live_and_not_found(self, client: TestClient):
        db = SessionLocal()
        db.add(
            TelemetryRecord(
                time=datetime.now(timezone.utc),
                machine_id="conveyor",
                state="RUNNING",
                voltage=415.0,
                current=18.5,
                power_kw=11.2,
                power_factor=0.84,
                energy_kwh=102.5,
            )
        )
        db.commit()
        db.close()

        # Valid machine
        response = client.get("/machines/conveyor/live")
        assert response.status_code == 200
        data = response.json()
        assert data["machine_id"] == "conveyor"
        assert data["power_kw"] == 11.2

        # Invalid machine ID -> 404
        bad_resp = client.get("/machines/unknown_machine_999/live")
        assert bad_resp.status_code == 404

    def test_waste_events_endpoint(self, client: TestClient):
        response = client.get("/waste-events?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_forecast_endpoint(self, client: TestClient):
        response = client.get("/forecast?machine_id=PLANT&granularity=HOURLY")
        assert response.status_code == 200
        data = response.json()
        assert data["machine_id"] == "PLANT"
        assert len(data["predictions"]) == 24
        assert "predicted_kw" in data["predictions"][0]
        assert "upper_bound_kw" in data["predictions"][0]

    def test_recommendations_endpoint(self, client: TestClient):
        response = client.get("/recommendations")
        assert response.status_code == 200
        recs = response.json()
        assert len(recs) >= 1
        top_rec = recs[0]
        assert "action" in top_rec
        assert "estimated_monthly_inr_saved" in top_rec
        assert "co2_avoided_kg" in top_rec

    def test_plant_summary_endpoint(self, client: TestClient):
        response = client.get("/summary")
        assert response.status_code == 200
        data = response.json()
        assert "todays_kwh" in data
        assert "todays_cost_inr" in data
        assert "todays_co2_kg" in data
        assert "monthly_savings_potential_inr" in data
