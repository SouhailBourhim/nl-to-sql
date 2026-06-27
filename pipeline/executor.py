from dataclasses import dataclass

from sqlalchemy import text

import config
from db.connection import engine
from db.schema_introspect import get_known_tables
from pipeline.safety import ensure_row_limit, validate_known_tables, validate_read_only


@dataclass
class ExecutionResult:
    columns: list[str]
    rows: list[tuple]


@dataclass
class ExecutionError:
    message: str
    sql: str


def execute_sql(sql: str, known_tables: set[str] | None = None) -> ExecutionResult | ExecutionError:
    try:
        validate_read_only(sql)
        validate_known_tables(sql, known_tables if known_tables is not None else get_known_tables())
    except Exception as exc:
        return ExecutionError(message=str(exc), sql=sql)

    safe_sql = ensure_row_limit(sql)

    try:
        # SQLAlchemy Connection commits nothing here since the statement is
        # read-only; the `with` block just returns the connection to the pool.
        with engine.connect() as conn:
            # Bounds actual query cost (not just rows returned) by killing a
            # runaway query at the database level. SQLite has no equivalent
            # setting, so this only applies when actually running Postgres.
            if engine.dialect.name == "postgresql":
                conn.execute(text(f"SET statement_timeout = {config.STATEMENT_TIMEOUT_MS}"))
            result = conn.execute(text(safe_sql))
            columns = list(result.keys())
            rows = result.fetchall()
        return ExecutionResult(columns=columns, rows=[tuple(row) for row in rows])
    except Exception as exc:
        return ExecutionError(message=str(exc), sql=safe_sql)
