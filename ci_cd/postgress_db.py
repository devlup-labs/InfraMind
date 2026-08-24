
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]  

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def ensure_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS errors (
                id           BIGSERIAL PRIMARY KEY,
                time         TIMESTAMPTZ NOT NULL DEFAULT now(),
                error_value  DOUBLE PRECISION NOT NULL,
                solved       BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))


def add_error(error_value: float, solved: bool = False):
    """Inserts a new row (node) into the errors table."""
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO errors (error_value, solved)
                VALUES (:error_value, :solved)
            """),
            {"error_value": error_value, "solved": solved},
        )
    print(f"[OK] added error_value={error_value} solved={solved}")