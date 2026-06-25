import streamlit as st

from db.schema_introspect import get_schema_text
from llm.ollama_backend import OllamaBackend
from pipeline.executor import execute_sql, ExecutionResult
from pipeline.explainer import explain
from pipeline.retry import PipelineFailure, PipelineResult, generate_and_execute

st.set_page_config(page_title="NL to SQL", layout="wide")


@st.cache_resource
def get_backend():
    return OllamaBackend()


@st.cache_data
def get_schema():
    return get_schema_text()


backend = get_backend()
schema_text = get_schema()

with st.sidebar:
    st.header("Connected schema")
    st.caption("Introspected live from the database via SQLAlchemy reflection.")
    st.code(schema_text, language="sql")
    if st.button("Refresh schema"):
        get_schema.clear()
        st.rerun()

st.title("NL to SQL")
question = st.text_input("Ask a question about the data", placeholder="Which breed has the most dogs?")

if question:
    with st.spinner("Generating SQL..."):
        outcome = generate_and_execute(backend, question, schema_text)

    if isinstance(outcome, PipelineFailure):
        st.error(
            f"Couldn't produce a working query after {outcome.attempts} attempts.\n\n"
            f"Last SQL tried:\n```sql\n{outcome.last_sql}\n```\n\nLast error: {outcome.last_error}"
        )
    else:
        st.subheader("Generated SQL")
        edited_sql = st.text_area("Edit and re-run if needed", value=outcome.sql, height=100)

        if edited_sql != outcome.sql:
            run_clicked = st.button("Run edited query")
        else:
            run_clicked = False

        active_sql = edited_sql if run_clicked else outcome.sql
        active_result = execute_sql(active_sql) if run_clicked else outcome.result

        if isinstance(active_result, ExecutionResult):
            st.subheader("Result")
            st.dataframe(
                [dict(zip(active_result.columns, row)) for row in active_result.rows],
                use_container_width=True,
            )

            with st.spinner("Writing explanation..."):
                answer = explain(backend, question, active_sql, active_result)
            st.subheader("Answer")
            st.write(answer)
        else:
            st.error(f"Query failed: {active_result.message}")
