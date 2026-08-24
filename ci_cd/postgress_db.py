
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]  

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def ensure_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS errors{
            metric_name VARCHAR(100) NOT NULL ;
            error_id PRIMARY KEY;
            time TIMESTAMPTZ NOT NULL DEFAULT now() ;
            error INTEGER NOT NULL;
            solved BOOLEAN NOT NULL DEFAULT FALSE;

}
        """))


def add_error(metric_name :str , error_value: float, solved: bool = False):
    """Inserts a new row (node) into the errors table."""
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO errors (metric_name , error_value, solved)
                VALUES (:metric_name , :error_value, :solved)
            """),
            {"metric_name":metric_name  , "error_value": error_value, "solved": solved},
        )
    print(f"[OK] added metric_name ={metric_name} error_value={error_value} solved={solved} ")