from db.schema_introspect import get_schema_text
from pipeline.executor import ExecutionError, execute_sql
from pipeline.explainer import explain
from pipeline.retry import PipelineFailure, PipelineResult, generate_and_execute
from tests.fakes import FakeLLMBackend


def test_generate_and_execute_succeeds_on_first_attempt():
    backend = FakeLLMBackend(["SELECT COUNT(*) AS n FROM customers"])
    schema = get_schema_text()

    outcome = generate_and_execute(backend, "How many customers are there?", schema)

    assert isinstance(outcome, PipelineResult)
    assert outcome.attempts == 1
    assert outcome.result.rows == [(3,)]


def test_generate_and_execute_retries_after_a_bad_query():
    backend = FakeLLMBackend(
        ["SELECT * FROM not_a_real_table", "SELECT COUNT(*) AS n FROM customers"]
    )
    schema = get_schema_text()

    outcome = generate_and_execute(backend, "How many customers are there?", schema)

    assert isinstance(outcome, PipelineResult)
    assert outcome.attempts == 2
    # the second call should have been told what went wrong with the first
    assert backend.generate_calls[1]["prior_error"] is not None


def test_generate_and_execute_gives_up_after_max_attempts():
    backend = FakeLLMBackend(["SELECT * FROM not_a_real_table"])
    schema = get_schema_text()

    outcome = generate_and_execute(backend, "How many customers are there?", schema)

    assert isinstance(outcome, PipelineFailure)
    assert outcome.attempts == len(backend.generate_calls)


def test_generate_and_execute_blocks_destructive_sql_without_retrying():
    backend = FakeLLMBackend(["DELETE FROM customers"])
    schema = get_schema_text()

    outcome = generate_and_execute(backend, "Remove churned customers", schema)

    assert isinstance(outcome, PipelineFailure)
    # a destructive query is rejected by the safety check every attempt --
    # confirms the retry loop never lets it through even once
    assert "SELECT or WITH" in outcome.last_error


def test_explain_uses_backend_explanation():
    backend = FakeLLMBackend([], explanation="There are 3 customers.")
    schema = get_schema_text()
    outcome = generate_and_execute(FakeLLMBackend(["SELECT COUNT(*) AS n FROM customers"]), "x", schema)

    answer = explain(backend, "How many customers?", outcome.sql, outcome.result)

    assert answer == "There are 3 customers."


def test_execute_sql_rejects_hallucinated_table():
    result = execute_sql("SELECT * FROM invoices")

    assert isinstance(result, ExecutionError)
    assert "invoices" in result.message


def test_generate_and_execute_recovers_from_backend_exception():
    # A network error/rate limit/malformed API response raises rather than
    # returning bad SQL -- the retry loop should treat that as retryable
    # too, not let it crash the whole request (this is what actually
    # happened with a live 429 from NVIDIA's API before this fix).
    backend = FakeLLMBackend(
        ["SELECT COUNT(*) AS n FROM customers"], raise_on_attempts={1}
    )
    schema = get_schema_text()

    outcome = generate_and_execute(backend, "How many customers are there?", schema)

    assert isinstance(outcome, PipelineResult)
    assert outcome.attempts == 2


def test_generate_and_execute_fails_cleanly_if_backend_always_raises():
    backend = FakeLLMBackend([], raise_on_attempts={1, 2, 3, 4})
    schema = get_schema_text()

    outcome = generate_and_execute(backend, "How many customers are there?", schema)

    assert isinstance(outcome, PipelineFailure)
    assert "simulated transport failure" in outcome.last_error
