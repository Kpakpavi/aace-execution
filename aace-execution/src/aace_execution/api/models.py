from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScoringFactor(BaseModel):
    factor_name: str
    factor_type: str
    weight: float


class ScoreRange(BaseModel):
    min: float
    max: float


class ScoringFactorSet(BaseModel):
    scoring_factors: list[ScoringFactor]
    score_range: ScoreRange
    normalization_method: str | None = None
    tie_break_order: list[str] = Field(default_factory=list)


class DiscrepancyRuleSet(BaseModel):
    rule_id: str
    threshold_method: str
    absolute_threshold: float


class Listing(BaseModel):
    listing_id: str
    source: str
    external_id: str
    price: float
    product_ref: str


class Observation(BaseModel):
    observation_id: str
    listing_ref: str
    source: str
    observed_price: float
    normalized_price: float
    observed_at: datetime


class RunPipelineRequest(BaseModel):
    pipeline_execution_id: str
    product_id: str
    product_name: str
    freshness_reference_timestamp: datetime
    alert_threshold: float
    opportunity_status: str
    eligible_opportunity_statuses: list[str]
    notification_type: str
    discrepancy_rule_set: DiscrepancyRuleSet
    scoring_factor_set: ScoringFactorSet
    listings: list[Listing]
    observations: list[Observation]
    duplicate_check_result: str
