"""Main execution entrypoint for the ingestion microservice."""

import argparse
import logging
import os
import signal
import sys
import time
from dotenv import load_dotenv

load_dotenv()

from database.connection import init_db
from ingestion.service import IngestionConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ingestion] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ingestion")


def main() -> None:
    parser = argparse.ArgumentParser(description="Energy Monitoring Ingestion Service")
    parser.add_argument(
        "--broker",
        default=os.getenv("MQTT_BROKER_HOST", "localhost"),
        help="MQTT broker host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MQTT_BROKER_PORT", "1883")),
        help="MQTT broker port (default: 1883)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Batch buffer size before flushing to TimescaleDB (default: 20)",
    )
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=1.0,
        help="Flush interval in seconds (default: 1.0)",
    )
    args = parser.parse_args()

    logger.info("Initializing database before starting ingestion...")
    init_db()

    consumer = IngestionConsumer(
        broker_host=args.broker,
        broker_port=args.port,
        batch_size=args.batch_size,
        flush_interval_seconds=args.flush_interval,
    )

    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received. Stopping consumer...")
        consumer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    consumer.start()
    logger.info("Ingestion service is running. Waiting for messages...")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        shutdown_handler(None, None)


if __name__ == "__main__":
    main()

