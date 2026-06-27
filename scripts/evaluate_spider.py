"""Execution-accuracy evaluation against the Spider benchmark.

Unlike tests/test_pipeline_integration.py (which checks pipeline *control
flow* with a canned FakeLLMBackend), this script measures real model
*accuracy*: for each Spider question, it runs our pipeline's generated SQL
and Spider's gold SQL against the same database and checks whether they
return the same data. It makes live LLM calls and is not part of `pytest`.

Usage:
    PYTHONPATH=. python scripts/evaluate_spider.py --limit 20
    PYTHONPATH=. python scripts/evaluate_spider.py --db dog_kennels --limit 50

Requires the Spider dataset at spider_data/ (see README -- not committed to
this repo) and whichever LLM backend is configured via LLM_BACKEND in .env.
"""
import argparse
import json
import os
import sys
from pathlib import Path

SPIDER_DIR = Path(__file__).resolve().parent.parent / "spider_data"


def _load_questions(db_id: str) -> list[dict]:
    with open(SPIDER_DIR / "dev.json") as f:
        dev = json.load(f)
    return [q for q in dev if q["db_id"] == db_id]


def _normalize_rows(rows: list[tuple]) -> list[tuple]:
    """Order-insensitive, column-order-insensitive comparison: sort each
    row's own values, then sort the list of rows. This is a simplification
    of Spider's official execution-accuracy metric (which handles column
    permutations more rigorously) -- good enough for a learning-project
    harness, not a byte-for-byte reproduction of the official eval script.
    """
    return sorted(tuple(sorted(str(v) for v in row)) for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="dog_kennels", help="Spider db_id to evaluate against")
    parser.add_argument("--limit", type=int, default=20, help="Number of questions to evaluate")
    parser.add_argument("--output", default=None, help="Optional path to write a JSON report")
    args = parser.parse_args()

    db_path = SPIDER_DIR / "database" / args.db / f"{args.db}.sqlite"
    if not db_path.exists():
        sys.exit(f"No Spider database found at {db_path}. Is the Spider dataset present?")

    # Must happen before config.py (or anything importing it) loads, same
    # reasoning as tests/conftest.py: DATABASE_URL is read once at import time.
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from sqlalchemy import text

    from db.connection import engine
    from db.schema_introspect import get_schema_text
    from llm.factory import get_backend
    from pipeline.retry import PipelineFailure, PipelineResult, generate_and_execute

    questions = _load_questions(args.db)[: args.limit]
    if not questions:
        sys.exit(f"No questions found for db_id='{args.db}' in spider_data/dev.json")

    schema = get_schema_text()
    backend = get_backend()

    results = []
    matched = 0
    gold_failed = 0
    generation_failed = 0

    for i, item in enumerate(questions, start=1):
        question = item["question"]
        gold_sql = item["query"]

        try:
            with engine.connect() as conn:
                gold_rows = [tuple(row) for row in conn.execute(text(gold_sql)).fetchall()]
        except Exception as exc:
            gold_failed += 1
            print(f"[{i}/{len(questions)}] SKIP (gold query itself failed on SQLite): {question}")
            results.append({"question": question, "gold_sql": gold_sql, "status": "gold_failed", "error": str(exc)})
            continue

        outcome = generate_and_execute(backend, question, schema)

        if isinstance(outcome, PipelineFailure):
            generation_failed += 1
            print(f"[{i}/{len(questions)}] FAIL (no working query after {outcome.attempts} attempts): {question}")
            results.append(
                {
                    "question": question,
                    "gold_sql": gold_sql,
                    "predicted_sql": outcome.last_sql,
                    "status": "generation_failed",
                    "error": outcome.last_error,
                }
            )
            continue

        is_match = _normalize_rows(outcome.result.rows) == _normalize_rows(gold_rows)
        matched += is_match
        status = "match" if is_match else "mismatch"
        print(f"[{i}/{len(questions)}] {status.upper()} (attempts={outcome.attempts}): {question}")
        results.append(
            {
                "question": question,
                "gold_sql": gold_sql,
                "predicted_sql": outcome.sql,
                "status": status,
                "attempts": outcome.attempts,
            }
        )

    evaluated = len(questions) - gold_failed
    accuracy = matched / evaluated if evaluated else 0.0

    print()
    print(f"Database: {args.db}")
    print(f"Questions evaluated: {evaluated}/{len(questions)} ({gold_failed} skipped: gold query failed on SQLite)")
    print(f"Generation failures (no working query): {generation_failed}")
    print(f"Execution-accuracy matches: {matched}/{evaluated} ({accuracy:.1%})")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(
                {"db": args.db, "evaluated": evaluated, "matched": matched, "accuracy": accuracy, "results": results},
                f,
                indent=2,
            )
        print(f"Full report written to {args.output}")


if __name__ == "__main__":
    main()
