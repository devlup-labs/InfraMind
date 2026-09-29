import os
from typing import Dict, List

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]

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
    _schema_ready = True


def _ensure_schema_once():
    # Deliberately lazy (not run at module import): importing this module
    # should never require a live DB connection, only actually using it does.
    if not _schema_ready:
        ensure_schema()


def add_error(metric_name: str, error_value: float, solved: bool = False):
    """Inserts a new row into the errors table."""
    _ensure_schema_once()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO errors (metric_name, error_value, solved)
                VALUES (:metric_name, :error_value, :solved)
            """),
            {"metric_name": metric_name, "error_value": error_value, "solved": solved},
        )
    print(f"[OK] added metric_name={metric_name} error_value={error_value} solved={solved}")


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