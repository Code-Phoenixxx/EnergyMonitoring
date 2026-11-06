"""Training pipeline for Isolation Forest anomaly detectors and LightGBM demand forecaster."""

import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
import pandas as pd
from sqlalchemy import text

from analytics.anomaly_detector import MachineAnomalyDetector
from analytics.forecaster import DemandForecaster
from database.connection import SessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [trainer] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("trainer")


def train_all_models() -> None:
    init_db()
    db = SessionLocal()

    try:
        logger.info("Fetching historical telemetry dataset from database...")
        df = pd.read_sql(
            text("SELECT time, machine_id, state, power_kw, voltage, current, power_factor FROM telemetry ORDER BY time ASC;"),
            con=db.connection(),
        )

        if df.empty or len(df) < 50:
            logger.warning("No sufficient telemetry in database. Run `python scripts/backfill.py` first!")
            return

        logger.info(f"Loaded {len(df)} historical observations across {df['machine_id'].nunique()} machines.")

        # 1. Train Isolation Forest per Machine
        detector = MachineAnomalyDetector()
        for mid in df["machine_id"].unique():
            mdf = df[df["machine_id"] == mid].reset_index(drop=True)
            logger.info(f"Training Isolation Forest for '{mid}' on {len(mdf)} records...")
            detector.train_machine_model(mid, mdf)

        # 2. Train LightGBM & Seasonal Naive Demand Forecaster for Plant Total
        forecaster = DemandForecaster()
        plant_df = (
            df.groupby("time")["power_kw"]
            .sum()
            .reset_index()
            .sort_values("time")
            .reset_index(drop=True)
        )

        logger.info(f"Training demand forecasting models for plant total ({len(plant_df)} intervals)...")
        metrics = forecaster.train_and_evaluate(plant_df, machine_id="PLANT", db=db)

        logger.info("=== Model Benchmark Results ===")
        for model_name, score in metrics.items():
            logger.info(f"  [{model_name}] MAE: {score['mae']} kW | RMSE: {score['rmse']} kW | MAPE: {score['mape']}%")

        logger.info("Model training pipeline completed successfully!")

    finally:
        db.close()


if __name__ == "__main__":
    train_all_models()
