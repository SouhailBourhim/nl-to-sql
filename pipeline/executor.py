from dataclasses import dataclass

from sqlalchemy import text

from db.connection import engine
from pipeline.safety import ensure_row_limit, validate_read_only


@dataclass
class ExecutionResult:
    columns: list[str]
    rows: list[tuple]


@dataclass
class ExecutionError:
    message: str
    sql: str


def execute_sql(sql: str) -> ExecutionResult | ExecutionError:
    try:
        validate_read_only(sql)
    except Exception as exc:
        return ExecutionError(message=str(exc), sql=sql)

    safe_sql = ensure_row_limit(sql)

    try:
        # SQLAlchemy Connection commits nothing here since the statement is
        # read-only; the `with` block just returns the connection to the pool.
        with engine.connect() as conn:
            result = conn.execute(text(safe_sql))
            columns = list(result.keys())
            rows = result.fetchall()
        return ExecutionResult(columns=columns, rows=[tuple(row) for row in rows])
    except Exception as exc:
        return ExecutionError(message=str(exc), sql=safe_sql)
