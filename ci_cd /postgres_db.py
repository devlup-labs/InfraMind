import math
import os
from typing import Dict, List

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set.")
if DATABASE_URL.startswith("postgres://"):      # some providers still hand out the old scheme
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Newer SQLAlchemy may default "postgresql://" to the psycopg (v3) driver. We ship psycopg2-binary,
# so pin the driver explicitly when it is installed.
if DATABASE_URL.startswith("postgresql://"):
    try:
        import psycopg2  # noqa: F401
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    except ImportError:
        pass

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

_schema_ready = False


def ensure_schema():
    global _schema_ready
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS errors (
                error_id     BIGSERIAL PRIMARY KEY,
                metric_name  VARCHAR(100) NOT NULL,
                time         TIMESTAMPTZ NOT NULL DEFAULT now(),
                error_value  DOUBLE PRECISION NOT NULL,
                solved       BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_errors_metric_time ON errors (metric_name, time DESC)"
        ))
    _schema_ready = True


def _ensure_schema_once():
    # Deliberately lazy (not run at module import): importing this module
    # should never require a live DB connection, only actually using it does.
    if not _schema_ready:
        ensure_schema()


def add_error(metric_name: str, error_value: float, solved: bool = False):
    """Inserts a new row into the errors table (non-finite values are ignored)."""
    if error_value is None or not math.isfinite(error_value):
        print(f"[SKIP] non-finite error for metric_name={metric_name}")
        return
    _ensure_schema_once()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO errors (metric_name, error_value, solved)
                VALUES (:metric_name, :error_value, :solved)
            """),
            {"metric_name": metric_name, "error_value": error_value, "solved": solved},
        )
    print(f"[OK] Added error: metric_name={metric_name} error_value={error_value} solved={solved}")


def get_error_history(limit_per_metric: int = 500) -> Dict[str, List[float]]:
    """Most recent `limit_per_metric` error values per metric, oldest first.

    Used by detect_concept_drift.py to replay each metric's error stream through
    a fresh ADWIN instance every run (state can't survive between CI runs).
    """
    _ensure_schema_once()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT metric_name, error_value
            FROM (
                SELECT
                    metric_name,
                    error_value,
                    time,
                    ROW_NUMBER() OVER (PARTITION BY metric_name ORDER BY time DESC) AS rn
                FROM errors
            ) ranked
            WHERE rn <= :limit
            ORDER BY metric_name, time ASC
        """), {"limit": limit_per_metric}).fetchall()

    history: Dict[str, List[float]] = {}
    for metric_name, error_value in rows:
        history.setdefault(metric_name, []).append(error_value)
    return history
