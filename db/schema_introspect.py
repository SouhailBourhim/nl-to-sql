from sqlalchemy import inspect

from db.connection import engine


def get_schema_text() -> str:
    """Serialize the connected database's schema as CREATE TABLE-style text.

    This format is what SQL-tuned models (sqlcoder included) were trained on,
    so feeding it into the prompt verbatim gives the LLM the same shape of
    context it saw during fine-tuning.
    """
    inspector = inspect(engine)
    tables_sql = []

    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        pk_columns = set(inspector.get_pk_constraint(table_name)["constrained_columns"])
        foreign_keys = inspector.get_foreign_keys(table_name)

        fk_by_column = {}
        for fk in foreign_keys:
            for local_col, remote_col in zip(fk["constrained_columns"], fk["referred_columns"]):
                fk_by_column[local_col] = f"{fk['referred_table']}({remote_col})"

        column_lines = []
        for col in columns:
            line = f"  {col['name']} {col['type']}"
            if col["name"] in pk_columns:
                line += " PRIMARY KEY"
            if col["name"] in fk_by_column:
                line += f" REFERENCES {fk_by_column[col['name']]}"
            column_lines.append(line)

        tables_sql.append(f"CREATE TABLE {table_name} (\n" + ",\n".join(column_lines) + "\n);")

    return "\n\n".join(tables_sql)


if __name__ == "__main__":
    print(get_schema_text())
