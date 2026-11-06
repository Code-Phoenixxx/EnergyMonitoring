"""Machine-level multivariate anomaly detection with Scikit-learn Isolation Forest."""

from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.cost_engine import CostAndCarbonEngine
from database.models import WasteEventRecord
from simulator.config_loader import load_yaml

logger = logging.getLogger("anomaly_detector")


class MachineAnomalyDetector:
    """Trains and executes Isolation Forest models per machine to detect power & operational anomalies."""

    def __init__(self, config_dir: Optional[Path] = None, models_dir: Optional[Path] = None) -> None:
        if config_dir is None:
            config_dir = Path("config")
        if models_dir is None:
            models_dir = Path("analytics/models")

        self.config_dir = config_dir
        self.models_dir = models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self.thresholds_cfg = load_yaml(config_dir / "thresholds.yaml")
        if_cfg = self.thresholds_cfg.get("anomalies", {}).get("isolation_forest", {})
        self.contamination = float(if_cfg.get("contamination", 0.03))
        self.n_estimators = int(if_cfg.get("n_estimators", 100))
        self.random_state = int(if_cfg.get("random_state", 42))

        # In-memory dictionary of loaded IsolationForest models: machine_id -> model
        self.models: Dict[str, IsolationForest] = {}
        self.cost_engine = CostAndCarbonEngine(config_dir)
        self.load_models()

    def get_model_path(self, machine_id: str) -> Path:
        return self.models_dir / f"iforest_{machine_id}.joblib"

    def load_models(self) -> None:
        """Load pre-trained Isolation Forest models from disk."""
        for file in self.models_dir.glob("iforest_*.joblib"):
            machine_id = file.stem.replace("iforest_", "")
            try:
                self.models[machine_id] = joblib.load(file)
                logger.info(f"Loaded Isolation Forest model for {machine_id}")
            except Exception as e:
                logger.warning(f"Could not load model {file}: {e}")

    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:
        """Engineer required ML features from raw telemetry observations.

        Features: power, current, power factor, rolling mean/std (window 15), hour of day.
        """
        feats = pd.DataFrame(index=df.index)
        feats["power_kw"] = df["power_kw"].astype(float)
        feats["current"] = df["current"].astype(float)
        feats["power_factor"] = df["power_factor"].astype(float)
        feats["hour"] = pd.to_datetime(df["time"]).dt.hour

        # Rolling statistics (min_periods=1)
        feats["rolling_mean_power"] = feats["power_kw"].rolling(window=15, min_periods=1).mean()
        feats["rolling_std_power"] = feats["power_kw"].rolling(window=15, min_periods=1).std().fillna(0.0)

        return feats

    def train_machine_model(self, machine_id: str, historical_df: pd.DataFrame) -> None:
        """Train an Isolation Forest model on normal-operation telemetry for a machine."""
        if historical_df.empty or len(historical_df) < 50:
            logger.warning(f"Insufficient training samples for {machine_id} ({len(historical_df)} rows).")
            return

        # Filter for nominal running / active states to learn normal operational baseline
        normal_data = historical_df[historical_df["state"].isin(["RUNNING", "IDLE"])]
        if len(normal_data) < 30:
            normal_data = historical_df

        features = self.extract_features(normal_data)

        model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
            n_jobs=-1,
        )
        model.fit(features)

        self.models[machine_id] = model
        joblib.dump(model, self.get_model_path(machine_id))
        logger.info(f"Trained & saved Isolation Forest for machine '{machine_id}' on {len(features)} samples.")

    def score_telemetry(
        self,
        machine_id: str,
        current_reading: Dict,
        rolling_buffer: List[Dict],
        db: Optional[Session] = None,
    ) -> Tuple[bool, float, Optional[WasteEventRecord]]:
        """Score an incoming live telemetry observation with the trained Isolation Forest.

        Returns:
            Tuple of (is_anomaly, severity_score, WasteEventRecord)
        """
        model = self.models.get(machine_id)
        if not model:
            # Fallback heuristic if ML model is not yet trained
            power = float(current_reading.get("power_kw", 0.0))
            is_anom = current_reading.get("state") == "FAULT" or power > 200.0
            return is_anom, 0.8 if is_anom else 0.0, None

        # Build local dataframe from buffer + current reading
        records = rolling_buffer + [current_reading]
        df = pd.DataFrame(records)
        features = self.extract_features(df).tail(1)

        # decision_function: lower means more abnormal (<0 is anomaly)
        raw_score = model.decision_function(features)[0]
        prediction = model.predict(features)[0]  # -1 for anomaly, 1 for normal

        is_anomaly = prediction == -1

        # Transform raw score to 0.0 - 1.0 severity score (where 1.0 is most severe anomaly)
        severity_score = round(max(0.0, min(1.0, 0.5 - (raw_score * 2.0))), 3)

        event = None
        if is_anomaly and severity_score >= 0.50:
            ts = pd.to_datetime(current_reading["time"]).to_pydatetime()
            power_kw = float(current_reading["power_kw"])
            severity_label = "HIGH" if severity_score >= 0.75 else "MEDIUM"

            desc = (
                f"Multi-variate anomaly detected on '{machine_id}' by Isolation Forest. "
                f"Active Draw: {power_kw:.1f} kW, PF: {current_reading.get('power_factor', 0.85):.2f}, "
                f"Anomaly Severity: {severity_score:.2f}."
            )

            # Estimate wasted power during anomaly spike (5 mins window = 0.083h)
            wasted_kwh = max(1.0, power_kw * 0.083)
            cost = self.cost_engine.calculate_cost(wasted_kwh, ts)

            event = WasteEventRecord(
                event_type="ANOMALY",
                machine_id=machine_id,
                start_time=ts,
                end_time=ts,
                kwh_wasted=round(wasted_kwh, 3),
                cost_inr=round(cost, 2),
                severity=severity_label,
                description=desc,
            )

            if db:
                db.add(event)
                db.commit()
                logger.warning(f"Recorded Anomaly Event on {machine_id}: {desc}")

        return is_anomaly, severity_score, event

