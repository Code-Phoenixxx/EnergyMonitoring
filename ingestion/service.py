"""MQTT telemetry ingestion consumer with batch insertion and resilience."""

from datetime import datetime
import json
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional
import paho.mqtt.client as mqtt
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.connection import SessionLocal, resolve_db_host
from database.models import TelemetryRecord
from simulator.models import MachineTelemetry
from simulator.publisher import resolve_broker_host

logger = logging.getLogger("ingestion")


class IngestionConsumer:
    """Consumes telemetry from MQTT broker, validates payloads, and batch-inserts into database."""

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        topic: str = "factory/+/telemetry",
        batch_size: int = 20,
        flush_interval_seconds: float = 1.0,
    ) -> None:
        """Initialize IngestionConsumer.

        Args:
            broker_host: MQTT broker host.
            broker_port: MQTT broker port.
            topic: Wildcard topic subscription.
            batch_size: Maximum messages to buffer before forcing database insert.
            flush_interval_seconds: Maximum time to buffer messages before flush.
        """
        self.broker_host = resolve_broker_host(broker_host, broker_port)
        self.broker_port = broker_port
        self.topic = topic
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds

        self.msg_queue: queue.Queue = queue.Queue(maxsize=10000)
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.total_processed = 0
        self.total_errors = 0

        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="energy_ingestion_service",
            )
        except AttributeError:
            self.client = mqtt.Client(client_id="energy_ingestion_service")

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client: Any, userdata: Any, *args: Any, **kwargs: Any) -> None:
        rc = args[1] if len(args) > 1 else (args[0] if len(args) > 0 else 0)
        rc_code = getattr(rc, "value", rc)
        if rc_code == 0:
            logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            self.client.subscribe(self.topic, qos=1)
            logger.info(f"Subscribed to telemetry topic: {self.topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker, code: {rc_code}")

    def _on_disconnect(self, client: Any, userdata: Any, *args: Any, **kwargs: Any) -> None:
        logger.warning(f"Disconnected from MQTT broker. Automatic reconnect active.")

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload_str = msg.payload.decode("utf-8")
            data = json.loads(payload_str)
            # Validate with Pydantic
            telemetry = MachineTelemetry(**data)
            self.msg_queue.put(telemetry, block=False)
        except json.JSONDecodeError as jde:
            self.total_errors += 1
            logger.warning(f"Malformed JSON on {msg.topic}: {jde}")
        except ValidationError as ve:
            self.total_errors += 1
            logger.warning(f"Pydantic validation rejected message on {msg.topic}: {ve}")
        except queue.Full:
            self.total_errors += 1
            logger.error("Ingestion buffer full! Dropping incoming message.")
        except Exception as e:
            self.total_errors += 1
            logger.error(f"Unexpected error processing message on {msg.topic}: {e}")

    def _batch_insert_loop(self) -> None:
        """Background thread worker to flush queued messages to database."""
        logger.info("Batch insertion worker thread started.")
        buffer: List[MachineTelemetry] = []
        last_flush = time.time()

        while self.running or not self.msg_queue.empty():
            try:
                # Wait up to 0.2s for new items
                item = self.msg_queue.get(timeout=0.2)
                buffer.append(item)
            except queue.Empty:
                pass

            now = time.time()
            time_to_flush = (now - last_flush) >= self.flush_interval_seconds
            size_to_flush = len(buffer) >= self.batch_size

            if buffer and (size_to_flush or time_to_flush or not self.running):
                self._flush_buffer(buffer)
                buffer.clear()
                last_flush = now

        logger.info("Batch insertion worker thread finished.")

    def _flush_buffer(self, items: List[MachineTelemetry]) -> None:
        """Insert batch of records into database with error handling."""
        if not items:
            return

        db: Session = SessionLocal()
        try:
            records = [
                TelemetryRecord(
                    time=datetime.fromisoformat(item.timestamp.replace("Z", "+00:00")),
                    machine_id=item.machine_id,
                    state=item.state,
                    voltage=item.voltage,
                    current=item.current,
                    power_kw=item.power_kw,
                    power_factor=item.power_factor,
                    energy_kwh=item.energy_kwh,
                )
                for item in items
            ]
            db.bulk_save_objects(records)
            db.commit()
            self.total_processed += len(items)
            logger.debug(f"Flushed {len(items)} telemetry records to database. Total: {self.total_processed}")
        except Exception as e:
            db.rollback()
            self.total_errors += len(items)
            logger.error(f"Failed to bulk-insert {len(items)} records: {e}")
        finally:
            db.close()

    def start(self) -> None:
        """Start ingestion service and network loop."""
        self.running = True
        self.worker_thread = threading.Thread(target=self._batch_insert_loop, daemon=True)
        self.worker_thread.start()

        logger.info(f"Connecting to broker {self.broker_host}:{self.broker_port}...")
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        """Stop ingestion service cleanly."""
        logger.info("Stopping IngestionConsumer...")
        self.running = False
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=3.0)
        logger.info(f"IngestionConsumer stopped. Processed: {self.total_processed}, Errors: {self.total_errors}")

