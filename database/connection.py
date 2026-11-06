"""Database engine, connection session management, and schema initialization."""

import logging
import os
from pathlib import Path
import platform
import socket
import subprocess
from typing import Generator
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from database.models import Base

load_dotenv()
logger = logging.getLogger(__name__)


_CACHED_WSL_IP = None


def get_wsl_ip() -> str | None:
    """Retrieve and cache WSL2 virtual IP address on Windows."""
    global _CACHED_WSL_IP
    if _CACHED_WSL_IP is not None:
        return _CACHED_WSL_IP
    if platform.system() == "Windows":
        try:
            wsl_out = subprocess.check_output(["wsl", "hostname", "-I"], text=True, timeout=4).strip()
            if wsl_out:
                _CACHED_WSL_IP = wsl_out.split()[0]
                return _CACHED_WSL_IP
        except Exception:
            pass
    return None


def resolve_db_host(host: str, port: int) -> str:
    """Resolve database host, automatically detecting WSL IP on Windows if needed."""
    if platform.system() == "Windows" and host in ("localhost", "127.0.0.1"):
        wsl_ip = get_wsl_ip()
        if wsl_ip:
            try:
                with socket.create_connection((wsl_ip, port), timeout=1.0):
                    return wsl_ip
            except Exception:
                pass

    try:
        with socket.create_connection((host, port), timeout=0.5):
            return host
    except (OSError, socket.error):
        pass

    return host


def get_database_url() -> str:
    """Construct or resolve the database connection URL."""
    raw_url = os.getenv("DATABASE_URL")
    if raw_url:
        return raw_url

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres_password_123")
    host = resolve_db_host(os.getenv("DATABASE_HOST", "localhost"), 5432)
    port = int(os.getenv("DATABASE_PORT", "5432"))
    db = os.getenv("POSTGRES_DB", "energy_monitoring")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


# Create engine with fallback capability
db_url = get_database_url()
logger.info(f"Configuring database engine for {db_url.split('@')[-1] if '@' in db_url else db_url}")

try:
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
except Exception as e:
    logger.warning(f"Failed to create PostgreSQL engine ({e}). Falling back to SQLite.")
    os.makedirs("data", exist_ok=True)
    engine = create_engine("sqlite:///data/energy_monitoring.db", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database tables, hypertables, and continuous aggregates."""
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)

    # If connected to PostgreSQL/TimescaleDB, execute Timescale-specific DDL
    if "postgresql" in str(engine.url):
        schema_file = Path(__file__).parent / "schema.sql"
        if schema_file.exists():
            with open(schema_file, "r", encoding="utf-8") as f:
                sql_content = f.read()

            with engine.connect() as conn:
                # Execute individual blocks or entire script
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
                    conn.commit()
                    logger.info("TimescaleDB extension verified/enabled.")
                except Exception as ext_err:
                    logger.warning(f"TimescaleDB extension notice: {ext_err}")

                try:
                    # Execute hypertable conversion if not already created
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                                PERFORM create_hypertable('telemetry', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
                            END IF;
                        END $$;
                    """))
                    conn.commit()
                    logger.info("Telemetry hypertable verified.")
                except Exception as ht_err:
                    logger.debug(f"Hypertable notice: {ht_err}")

    logger.info("Database schema initialization complete.")

