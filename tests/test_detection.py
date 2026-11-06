"""Unit tests for idle waste detection, peak demand calculation, and anomaly scoring."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from analytics.cost_engine import CostAndCarbonEngine
from analytics.idle_detector import IdleWasteDetector
from analytics.peak_detector import PeakDemandDetector
from database.connection import SessionLocal
from database.models import TelemetryRecord, WasteEventRecord


@pytest.fixture
def test_db():
    """Database fixture for detection tests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def cost_engine():
    return CostAndCarbonEngine(Path("config"))


class TestDetectionLogic:
    """Test suite for idle loss, peak breach, and anomaly identification."""

    def test_idle_waste_threshold_flagging(self, test_db, cost_engine):
        """Verify idle power exceeding rated % threshold flags waste after duration."""
        detector = IdleWasteDetector(config_dir=Path("config"), cost_engine=cost_engine)

        # Compressor rated at 37 kW, idle threshold override is 20% = 7.4 kW
        start_t = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)

        # Draw 12 kW (unloaded air leak draw) for 15 minutes (> 10 min threshold)
        captured_event = None
        for i in range(16):
            t = start_t + timedelta(minutes=i)
            event = detector.inspect_reading(
                machine_id="air_compressor",
                state="IDLE",
                power_kw=12.0,
                timestamp=t,
                db=test_db,
            )
            if event:
                captured_event = event

        # Verify an idle waste incident was generated and recorded
        assert captured_event is not None
        assert captured_event.event_type == "IDLE_WASTE"
        assert captured_event.machine_id == "air_compressor"
        assert captured_event.kwh_wasted > 0.0
        assert captured_event.cost_inr > 0.0
        assert "air_compressor" in captured_event.description

    def test_idle_power_below_threshold_is_ignored(self, test_db, cost_engine):
        """Verify normal low idle draw does not generate a waste event."""
        detector = IdleWasteDetector(config_dir=Path("config"), cost_engine=cost_engine)

        start_t = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)
        # CNC machine rated at 22 kW; threshold is 8% = 1.76 kW. Draw 1.0 kW
        for i in range(20):
            t = start_t + timedelta(minutes=i)
            event = detector.inspect_reading(
                machine_id="cnc_machine",
                state="IDLE",
                power_kw=1.0,
                timestamp=t,
                db=test_db,
            )
            assert event is None

    def test_peak_demand_rolling_breach(self, test_db, cost_engine):
        """Verify peak detector identifies 15-minute rolling average exceeding 250 kW."""
        peak_detector = PeakDemandDetector(config_dir=Path("config"), cost_engine=cost_engine)

        now = datetime(2026, 11, 4, 15, 0, 0, tzinfo=timezone.utc)
        # Insert 15 minutes of plant telemetry averaging 270 kW (above 250 kW limit)
        for m in range(15):
            sample_time = now - timedelta(minutes=m)
            test_db.add(
                TelemetryRecord(
                    time=sample_time,
                    machine_id="induction_furnace",
                    state="RUNNING",
                    voltage=415.0,
                    current=380.0,
                    power_kw=270.0,
                    power_factor=0.92,
                    energy_kwh=500.0,
                )
            )
        test_db.commit()

        event = peak_detector.evaluate_rolling_demand(test_db, current_time=now)
        assert event is not None
        assert event.event_type == "PEAK_DEMAND"
        assert event.machine_id == "PLANT"
        assert event.cost_inr > 0.0
        assert "Plant Peak Demand Breach" in event.description
