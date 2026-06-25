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


def ensure_row_limit(sql: str, max_rows: int = config.MAX_RESULT_ROWS) -> str:
    """Cap result size even if the LLM forgot a LIMIT, so a careless
    'select all transactions' question can't pull millions of rows."""
    stripped = sql.strip().rstrip(";").strip()
    if re.search(r"\blimit\s+\d+\s*$", stripped, re.IGNORECASE):
        return stripped
    return f"{stripped} LIMIT {max_rows}"
