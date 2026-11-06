"""Background analytics worker executing waste detection, peak surveillance, and forecasting."""

import argparse
import logging
import signal
import sys
import time
from dotenv import load_dotenv

load_dotenv()
from datetime import datetime, timedelta, timezone
import pandas as pd
from sqlalchemy import text

from analytics.anomaly_detector import MachineAnomalyDetector
from analytics.cost_engine import CostAndCarbonEngine
from analytics.forecaster import DemandForecaster
from analytics.idle_detector import IdleWasteDetector
from analytics.peak_detector import PeakDemandDetector
from analytics.recommendations import RecommendationEngine
from database.connection import SessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [analytics-worker] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("analytics_worker")


def run_worker_loop(interval_seconds: float = 5.0) -> None:
    """Continuously execute detection engines and periodic analytics workflows."""
    cost_engine = CostAndCarbonEngine()
    idle_detector = IdleWasteDetector(cost_engine=cost_engine)
    peak_detector = PeakDemandDetector(cost_engine=cost_engine)
    anomaly_detector = MachineAnomalyDetector()
    forecaster = DemandForecaster()
    rec_engine = RecommendationEngine(cost_engine=cost_engine)

    last_forecast_time = 0.0
    last_processed_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    rolling_buffers = {}

    running = True

    def shutdown(signum, frame):
        nonlocal running
        logger.info("Analytics worker stopping...")
        running = False
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Analytics worker initialized and monitoring live stream...")

    while running:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)

            # 1. Fetch recent telemetry records since last cycle
            records = db.execute(text("""
                SELECT time, machine_id, state, power_kw, voltage, current, power_factor
                FROM telemetry
                WHERE time > :last_time
                ORDER BY time ASC
                LIMIT 100;
            """), {"last_time": last_processed_time}).fetchall()

            for r in records:
                t, mid, state, power, v, curr, pf = r[0], r[1], r[2], float(r[3]), float(r[4]), float(r[5]), float(r[6])
                last_processed_time = max(last_processed_time, t)

                # Idle Waste Check
                idle_detector.inspect_reading(mid, state, power, t, db=db)

                # Anomaly Detection Check
                if mid not in rolling_buffers:
                    rolling_buffers[mid] = []
                sample = {"time": t, "power_kw": power, "voltage": v, "current": curr, "power_factor": pf, "state": state}
                anomaly_detector.score_telemetry(mid, sample, rolling_buffers[mid], db=db)
                rolling_buffers[mid].append(sample)
                if len(rolling_buffers[mid]) > 30:
                    rolling_buffers[mid].pop(0)

            # 2. Evaluate 15-Minute Peak Plant Demand
            peak_detector.evaluate_rolling_demand(db, current_time=now)

            # 3. Periodic Forecast & Recommendation Refresh (every 5 minutes or initial run)
            if time.time() - last_forecast_time > 300.0:
                logger.info("Running periodic forecast generation and recommendation synthesis...")
                # Fetch last 24h plant data for forecasting
                plant_df = pd.read_sql(text("""
                    SELECT time, SUM(power_kw) as power_kw
                    FROM telemetry
                    WHERE time >= NOW() - INTERVAL '24 hours'
                    GROUP BY time ORDER BY time ASC;
                """), con=db.connection())

                if not plant_df.empty and len(plant_df) >= 10:
                    forecaster.generate_24h_forecast(plant_df, machine_id="PLANT", db=db)

                rec_engine.generate_recommendations(db)
                last_forecast_time = time.time()

        except Exception as e:
            logger.error(f"Error in analytics worker cycle: {e}")
            db.rollback()
        finally:
            db.close()

        time.sleep(interval_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analytics Worker")
    parser.add_argument("--interval", type=float, default=5.0, help="Check interval in seconds")
    args = parser.parse_args()
    run_worker_loop(interval_seconds=args.interval)

