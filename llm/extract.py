import re


def extract_sql(raw_text: str) -> str:
    """Strip whatever wrapper a model puts around its SQL answer: a ```sql
    markdown fence (common with chat-instruct models), or sqlcoder's own
    [SQL]/[/SQL] template tokens echoed back in the output."""
    text = raw_text.strip()
    fence_match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1)
    text = re.sub(r"\[/?SQL\]", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(";").strip()
