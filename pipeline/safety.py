import re

import config

_ALLOWED_LEADING_KEYWORDS = ("select", "with")
_FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "grant", "revoke", "attach", "detach", "replace",
)


class UnsafeQueryError(ValueError):
    pass


def validate_read_only(sql: str) -> None:
    """The LLM turns arbitrary English into arbitrary SQL — this is the one
    place standing between that and a real database. Anything other than a
    single read-only SELECT/CTE statement is rejected outright, never executed.
    """
    stripped = sql.strip().rstrip(";").strip()

    if ";" in stripped:
        raise UnsafeQueryError("Multiple statements are not allowed.")

    first_word = re.match(r"\s*(\w+)", stripped)
    leading_keyword = first_word.group(1).lower() if first_word else ""

    if leading_keyword not in _ALLOWED_LEADING_KEYWORDS:
        raise UnsafeQueryError(f"Query must start with SELECT or WITH, got '{leading_keyword}'.")

    lowered = stripped.lower()
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise UnsafeQueryError(f"Forbidden keyword '{keyword}' found in query.")


def validate_known_tables(sql: str, known_tables: set[str]) -> None:
    """Catch a hallucinated table name with a clear error before sending the
    query to the database at all. This is regex-based, not a real SQL parser
    -- proportionate to the same threat model as validate_read_only (an LLM
    mistranslating English into a wrong query, not an adversarial attacker),
    where a fast, approximate check is more valuable than a precise one.

    CTE names (`WITH foo AS (...)`) are locally-defined, not real tables, so
    they're collected and excluded from the check rather than flagged.
    """
    stripped = sql.strip().rstrip(";").strip()
    lowered = stripped.lower()

    cte_names = {m.lower() for m in re.findall(r"\b(\w+)\s+as\s*\(", lowered)}

    # Allow schema-qualified names (e.g. "public.customers") by taking the
    # last dotted segment as the table name.
    referenced = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][\w.]*)", lowered)
    referenced = [name.rsplit(".", 1)[-1] for name in referenced]
    unknown = {name for name in referenced if name not in known_tables and name not in cte_names}

    if unknown:
        raise UnsafeQueryError(
            f"Query references unknown table(s): {', '.join(sorted(unknown))}. "
            f"Known tables: {', '.join(sorted(known_tables))}."
        )


def ensure_row_limit(sql: str, max_rows: int = config.MAX_RESULT_ROWS) -> str:
    """Cap result size even if the LLM forgot a LIMIT, so a careless
    'select all transactions' question can't pull millions of rows."""
    stripped = sql.strip().rstrip(";").strip()
    if re.search(r"\blimit\s+\d+\s*$", stripped, re.IGNORECASE):
        return stripped
    return f"{stripped} LIMIT {max_rows}"
