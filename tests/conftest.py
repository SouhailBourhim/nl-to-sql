import os
import tempfile

# Must happen before config.py (or anything that imports it) is imported
# anywhere in the test session -- config.DATABASE_URL is read once at import
# time, and db/connection.py builds its engine from that value immediately.
# Pointing tests at a throwaway SQLite file (not the real Postgres container)
# means the test suite never depends on Docker/Postgres being up.
_db_fd, _db_path = tempfile.mkstemp(suffix=".sqlite")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from db.connection import engine  # noqa: E402

_SCHEMA = """
CREATE TABLE plans (
    plan_id INTEGER PRIMARY KEY,
    plan_name TEXT NOT NULL,
    monthly_price REAL NOT NULL
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    plan_id INTEGER NOT NULL REFERENCES plans(plan_id),
    status TEXT NOT NULL
);

CREATE TABLE recharges (
    recharge_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    amount REAL NOT NULL
);
"""

_SEED = """
INSERT INTO plans VALUES (1, 'Basic', 9.99), (2, 'Premium', 39.99);
INSERT INTO customers VALUES
    (1, 'Amine', 1, 'active'),
    (2, 'Sara', 2, 'churned'),
    (3, 'Youssef', 1, 'active');
INSERT INTO recharges VALUES
    (1, 1, 10.0), (2, 1, 15.0), (3, 1, 12.0),
    (4, 2, 20.0), (5, 2, 25.0), (6, 2, 18.0), (7, 2, 22.0), (8, 2, 30.0), (9, 2, 14.0);
"""


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Creates the schema once per test session in the throwaway SQLite file."""
    with engine.begin() as conn:
        for statement in (_SCHEMA + _SEED).strip().split(";"):
            if statement.strip():
                conn.execute(text(statement))
    yield
    os.remove(_db_path)
