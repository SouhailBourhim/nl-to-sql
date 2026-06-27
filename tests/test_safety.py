import pytest

from pipeline.safety import UnsafeQueryError, ensure_row_limit, validate_known_tables, validate_read_only

KNOWN_TABLES = {"customers", "plans", "recharges"}


def test_validate_read_only_accepts_select():
    validate_read_only("SELECT * FROM customers")


def test_validate_read_only_accepts_with_cte():
    validate_read_only("WITH x AS (SELECT 1) SELECT * FROM x")


def test_validate_read_only_rejects_delete():
    with pytest.raises(UnsafeQueryError):
        validate_read_only("DELETE FROM customers WHERE 1=1")


def test_validate_read_only_rejects_multiple_statements():
    with pytest.raises(UnsafeQueryError):
        validate_read_only("SELECT 1; DROP TABLE customers")


def test_validate_known_tables_accepts_real_table():
    validate_known_tables("SELECT * FROM customers", KNOWN_TABLES)


def test_validate_known_tables_accepts_join():
    validate_known_tables(
        "SELECT * FROM customers JOIN plans ON customers.plan_id = plans.plan_id", KNOWN_TABLES
    )


def test_validate_known_tables_rejects_hallucinated_table():
    with pytest.raises(UnsafeQueryError):
        validate_known_tables("SELECT * FROM invoices", KNOWN_TABLES)


def test_validate_known_tables_allows_cte_name():
    sql = "WITH recent AS (SELECT * FROM customers) SELECT * FROM recent"
    validate_known_tables(sql, KNOWN_TABLES)


def test_validate_known_tables_allows_schema_qualified_name():
    validate_known_tables("SELECT * FROM public.customers", KNOWN_TABLES)


def test_ensure_row_limit_adds_limit_when_missing():
    assert ensure_row_limit("SELECT * FROM customers", max_rows=50) == "SELECT * FROM customers LIMIT 50"


def test_ensure_row_limit_leaves_existing_limit():
    sql = "SELECT * FROM customers LIMIT 10"
    assert ensure_row_limit(sql, max_rows=50) == sql
