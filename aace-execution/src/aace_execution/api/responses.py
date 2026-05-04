"""API response models for the AACE FastAPI layer.

Mirrors the shape returned by ``PipelineRunner.run`` (see
``aace_execution.pipeline.pipeline_runner.PipelineResult``).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StageOutcomeResponse(BaseModel):
    stage: str
    classification: str


class AuditResponse(BaseModel):
    pipeline_execution_id: str
    product_id: str | None = None
    final_result: str
    result_timestamp: str
    stage_outcomes: list[StageOutcomeResponse] = Field(default_factory=list)
    failure_stage: str | None = None
    failure_reason: str | None = None
    retriable: bool | None = None
    suppression_reason: str | None = None
    stop_stage: str | None = None
    stop_reason: str | None = None


class StageOutputsResponse(BaseModel):
    input_validation: dict[str, Any] | None = None
    discrepancy_detection: dict[str, Any] | None = None
    duplicate_check_result: str | None = None
    opportunity_scoring: dict[str, Any] | None = None
    alert_decision: dict[str, Any] | None = None


class RunPipelineResponse(BaseModel):
    result: str
    pipeline_execution_id: str
    product_id: str | None = None
    stage_outputs: StageOutputsResponse
    audit: AuditResponse
    retriable: bool | None = None
    failure_stage: str | None = None
    failure_reason: str | None = None
