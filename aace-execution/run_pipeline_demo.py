"""Minimal demo: run PipelineRunner once with an input loaded from a JSON file."""

from __future__ import annotations

import json
import sys
from datetime import datetime

from src.aace_execution.pipeline.pipeline_runner import PipelineRunner
from src.aace_execution.persistence.db import connect
from src.aace_execution.persistence.postgres_writer import PostgresWriter
from src.aace_execution.validators.input_validator import (
    InputValidator,
    ValidationContext,
)

ALLOWED_SOURCES = frozenset({"source_a", "source_b"})


def load_pipeline_input(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        pipeline_input = json.load(fh)

    ref_ts = pipeline_input.get("freshness_reference_timestamp")
    if isinstance(ref_ts, str):
        pipeline_input["freshness_reference_timestamp"] = datetime.fromisoformat(ref_ts)

    return pipeline_input


def validator_factory(pipeline_input: dict) -> InputValidator:
    ref_ts = pipeline_input["freshness_reference_timestamp"]
    context = ValidationContext(
        pipeline_execution_id=pipeline_input["pipeline_execution_id"],
        freshness_reference_timestamp=ref_ts,
        freshness_window_seconds=3600,
        allowed_sources=ALLOWED_SOURCES,
        validated_at=ref_ts,
    )
    return InputValidator(context)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python run_pipeline_demo.py <pipeline_input.json>", file=sys.stderr)
        sys.exit(2)

    pipeline_input = load_pipeline_input(sys.argv[1])

    connection = connect()
    try:
        writer = PostgresWriter(connection)
        runner = PipelineRunner(
            input_validator_factory=validator_factory,
            postgres_writer=writer,
        )
        result = runner.run(pipeline_input)
    finally:
        connection.close()
    print("final_result:", result.result)
    print("pipeline_execution_id:", result.pipeline_execution_id)
    print("product_id:", result.product_id)
    print("failure_stage:", result.failure_stage)
    print("failure_reason:", result.failure_reason)


if __name__ == "__main__":
    main()
