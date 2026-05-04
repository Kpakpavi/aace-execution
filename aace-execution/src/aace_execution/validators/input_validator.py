"""
Input Validator — Stage 1 of the AACE Opportunity Pipeline.

Contract: Contracts/INPUT_VALIDATOR_CONTRACT.md

This module validates every field in the pipeline input context and classifies
the result as VALID, INVALID, or PRECONDITION_FAILURE.

Determinism guarantee (Contract §10):
    The same input_context + the same ValidationContext always produce the same
    ValidationResult. No system clock is used for decisions. No randomness.
    No external calls.

What this module does NOT do (Contract §13):
    - Modify, normalise, or transform any input field.
    - Infer or default any missing value.
    - Call any external system, database, or API.
    - Use the system clock for freshness decisions.
    - Apply any business logic beyond structural validation.
    - Produce partial results (VALID with warnings).
    - Swallow exceptions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result classification — Contract §9
# ---------------------------------------------------------------------------

class ValidationResultType(str, Enum):
    """
    The three and only three result states the validator may produce.
    Contract §9: no other state exists.
    """
    VALID = "VALID"
    INVALID = "INVALID"
    PRECONDITION_FAILURE = "PRECONDITION_FAILURE"


# ---------------------------------------------------------------------------
# Validation categories — Contract §6
# ---------------------------------------------------------------------------

class ValidationCategory(str, Enum):
    """
    The eight ordered validation categories applied in strict sequence.
    A failure in any category halts validation; later categories are not checked.
    Contract §6, §7.5.
    """
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    REQUIRED_FIELD_VALIDATION = "REQUIRED_FIELD_VALIDATION"
    TYPE_VALIDATION = "TYPE_VALIDATION"
    VALUE_VALIDATION = "VALUE_VALIDATION"
    SOURCE_VALIDATION = "SOURCE_VALIDATION"
    TIMESTAMP_VALIDATION = "TIMESTAMP_VALIDATION"
    RELATIONSHIP_VALIDATION = "RELATIONSHIP_VALIDATION"
    COMPARISON_ELIGIBILITY = "COMPARISON_ELIGIBILITY"


# ---------------------------------------------------------------------------
# Rule identifiers — Contract §7
# ---------------------------------------------------------------------------

class ValidationRule(str, Enum):
    """
    Named identifiers for the ten validation rules in Contract §7.
    Every ValidationError must reference one of these.
    """
    NO_SILENT_ACCEPTANCE = "RULE_7_1_NO_SILENT_ACCEPTANCE"
    NO_SILENT_COERCION = "RULE_7_2_NO_SILENT_COERCION"
    NO_INFERENCE_OF_MISSING_VALUES = "RULE_7_3_NO_INFERENCE_OF_MISSING_VALUES"
    PRICE_STRICTLY_POSITIVE = "RULE_7_6_PRICE_STRICTLY_POSITIVE"
    SOURCE_MUST_BE_RECOGNIZED = "RULE_7_7_SOURCE_MUST_BE_RECOGNIZED"
    FRESHNESS_IS_MANDATORY = "RULE_7_8_FRESHNESS_IS_MANDATORY"
    RELATIONSHIPS_WITHIN_CONTEXT = "RULE_7_9_RELATIONSHIPS_WITHIN_CONTEXT"
    NO_DUPLICATE_SOURCE_OBSERVATIONS = "RULE_7_10_NO_DUPLICATE_SOURCE_OBSERVATIONS"


# ---------------------------------------------------------------------------
# Structured error — Contract §8.2
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationError:
    """
    A single field-level error entry in an INVALID result.

    Contract §8.2: every error must contain field, received_value, reason,
    and rule_violated. received_value must be redacted for sensitive data.
    """
    field: str
    received_value: Any       # redact if the field carries credentials or PII
    reason: str
    rule_violated: str        # a ValidationRule enum value


# ---------------------------------------------------------------------------
# Validation result dataclasses — Contract §8
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidResult:
    """
    Contract §8.1 — all eight validation categories passed.
    Authorises the pipeline to proceed to Stage 2 (Discrepancy Detection).
    """
    result: str               # always ValidationResultType.VALID
    validated_at: datetime
    input_identity: str
    observation_count: int
    source_count: int


@dataclass(frozen=True)
class InvalidResult:
    """
    Contract §8.2 — one or more field-level checks in Categories 1–7 failed.
    Halts the pipeline. Not retriable without correcting the input.
    """
    result: str               # always ValidationResultType.INVALID
    validated_at: datetime
    input_identity: str
    failure_category: str     # a ValidationCategory enum value
    errors: tuple[ValidationError, ...]


@dataclass(frozen=True)
class PreconditionFailureResult:
    """
    Contract §8.3 — input is structurally valid but fails Category 6 (stale
    timestamps) or Category 8 (insufficient distinct sources).

    retriable=True  → may become valid when fresher data is provided.
    retriable=False → configuration must be corrected before retrying.
    """
    result: str               # always ValidationResultType.PRECONDITION_FAILURE
    validated_at: datetime
    input_identity: str
    precondition_failed: str
    reason: str
    retriable: bool


# Union alias used throughout the module.
ValidationResult = ValidResult | InvalidResult | PreconditionFailureResult


# ---------------------------------------------------------------------------
# Execution context — Contract §10 Rule 3, §5
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationContext:
    """
    External parameters the validator needs that are NOT part of the business
    input itself. Must be provided by the pipeline coordinator.

    The validator must not derive any of these from the environment or from
    the system clock (Contract §10 Rule 3).

    Fields
    ------
    pipeline_execution_id:
        Unique identifier for the current pipeline run. Used only for logging.
    freshness_reference_timestamp:
        The reference point used to evaluate whether observations are fresh.
        Must be timezone-aware. Never replaced by a system clock reading.
    freshness_window_seconds:
        Maximum age in seconds an observation timestamp may have relative to
        freshness_reference_timestamp while still being considered fresh.
    allowed_sources:
        The spec-defined set of recognised source identifiers. An observation
        or listing source not in this set is invalid (Rule 7.7).
    """
    pipeline_execution_id: str
    freshness_reference_timestamp: datetime
    freshness_window_seconds: int
    allowed_sources: frozenset[str]
    validated_at: datetime


# ---------------------------------------------------------------------------
# Input Validator
# ---------------------------------------------------------------------------

class InputValidator:
    """
    Implements the full Input Validator contract
    (Contracts/INPUT_VALIDATOR_CONTRACT.md).

    Validates the complete structured input context for the Opportunity Pipeline
    Job. Produces exactly one ValidationResult per call.

    Usage
    -----
        context = ValidationContext(
            pipeline_execution_id="exec-001",
            freshness_reference_timestamp=datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc),
            freshness_window_seconds=3600,
            allowed_sources=frozenset({"source_a", "source_b"}),
        )
        validator = InputValidator(context)
        result = validator.validate(input_context)

    Guarantees
    ----------
    - Does not modify the input in any way (Contract §13).
    - Does not infer or default missing values (Contract §7.3).
    - Does not call external systems (Contract §13).
    - Does not use the system clock for freshness decisions (Contract §10 Rule 3).
    - Applies eight ordered categories; stops and collects all errors in the
      first failing category (Contract §6, §7.5).
    - Returns VALID, INVALID, or PRECONDITION_FAILURE — nothing else (Contract §9).
    """

    # Top-level keys required in every pipeline input context — Contract §5
    _REQUIRED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
        "product_id",
        "listings",
        "observations",
        "discrepancy_rule_set",
        "scoring_factor_set",
        "alert_threshold",
    })

    # Required fields per listing — Contract §5.2
    _REQUIRED_LISTING_FIELDS: tuple[str, ...] = (
        "listing_id",
        "source",
        "external_id",
        "price",
        "product_ref",
    )

    # Required fields per observation — Contract §5.3
    _REQUIRED_OBSERVATION_FIELDS: tuple[str, ...] = (
        "observation_id",
        "listing_ref",
        "source",
        "observed_price",
        "observed_at",
    )

    def __init__(self, context: ValidationContext) -> None:
        if context is None:
            raise ValueError("ValidationContext must not be None.")
        self._context = context

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def validate(self, input_context: Any) -> ValidationResult:
        """
        Execute all eight validation categories against input_context.

        Categories are run in the order defined by Contract §6. Validation
        stops at the first failing category; all errors within that category
        are collected and returned together (Contract §7.5).

        Parameters
        ----------
        input_context:
            The raw pipeline input as a structured dict. Not modified.

        Returns
        -------
        ValidationResult
            Exactly one of: ValidResult, InvalidResult, PreconditionFailureResult.

        Raises
        ------
        Any unhandled exception propagates to the caller unchanged (Contract §13:
        "Swallow exceptions" is explicitly forbidden).
        """
        # validated_at is supplied by the caller via ValidationContext so that
        # the result is fully deterministic for the same input (Contract §10).
        validated_at = self._context.validated_at
        input_identity = self._extract_input_identity(input_context)

        logger.info(
            "validation_start",
            extra={
                "pipeline_execution_id": self._context.pipeline_execution_id,
                "input_identity": input_identity,
                "validated_at": validated_at.isoformat(),
            },
        )

        # ------------------------------------------------------------------
        # Category 1 — Schema Validation
        # Contract §6 Category 1: overall structure must be present and parseable.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.SCHEMA_VALIDATION.value},
        )
        errors = self._validate_schema(input_context)
        if errors:
            return self._make_invalid(
                validated_at, input_identity,
                ValidationCategory.SCHEMA_VALIDATION, errors,
            )

        # ------------------------------------------------------------------
        # Category 2 — Required Field Validation
        # Contract §6 Category 2: all required fields must be present and non-null.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.REQUIRED_FIELD_VALIDATION.value},
        )
        errors = self._validate_required_fields(input_context)
        if errors:
            return self._make_invalid(
                validated_at, input_identity,
                ValidationCategory.REQUIRED_FIELD_VALIDATION, errors,
            )

        # ------------------------------------------------------------------
        # Category 3 — Type Validation
        # Contract §6 Category 3: all fields must be the correct type.
        # Rule 7.2: a string that looks like a number is not a number.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.TYPE_VALIDATION.value},
        )
        errors = self._validate_types(input_context)
        if errors:
            return self._make_invalid(
                validated_at, input_identity,
                ValidationCategory.TYPE_VALIDATION, errors,
            )

        # ------------------------------------------------------------------
        # Category 4 — Value Validation
        # Contract §6 Category 4: values must be within allowed ranges.
        # Rule 7.6: price must be strictly > 0.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.VALUE_VALIDATION.value},
        )
        errors = self._validate_values(input_context)
        if errors:
            return self._make_invalid(
                validated_at, input_identity,
                ValidationCategory.VALUE_VALIDATION, errors,
            )

        # ------------------------------------------------------------------
        # Category 5 — Source Validation
        # Contract §6 Category 5: all sources must belong to the allowed set.
        # Rule 7.7: unrecognised source is invalid even if non-empty.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.SOURCE_VALIDATION.value},
        )
        errors = self._validate_sources(input_context)
        if errors:
            return self._make_invalid(
                validated_at, input_identity,
                ValidationCategory.SOURCE_VALIDATION, errors,
            )

        # ------------------------------------------------------------------
        # Category 6 — Timestamp Validation
        # Contract §6 Category 6, Rule 7.8:
        #   Pass 1 — malformed timestamps → INVALID
        #   Pass 2 — stale timestamps    → PRECONDITION_FAILURE (retriable)
        # The freshness_reference_timestamp from the context is used exclusively.
        # The system clock is never read for this decision.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.TIMESTAMP_VALIDATION.value},
        )
        format_errors, stale_observation_ids = self._validate_timestamps(input_context)
        if format_errors:
            return self._make_invalid(
                validated_at, input_identity,
                ValidationCategory.TIMESTAMP_VALIDATION, format_errors,
            )
        if stale_observation_ids:
            reason = (
                f"Observation(s) with id(s) {sorted(stale_observation_ids)} are outside "
                f"the freshness window of {self._context.freshness_window_seconds} seconds "
                f"relative to reference timestamp "
                f"{self._context.freshness_reference_timestamp.isoformat()}. "
                "Fresh observations must be provided before the pipeline can proceed."
            )
            logger.warning(
                "validation_precondition_failure",
                extra={
                    "category": ValidationCategory.TIMESTAMP_VALIDATION.value,
                    "precondition_failed": "STALE_OBSERVATIONS",
                    "retriable": True,
                    "pipeline_execution_id": self._context.pipeline_execution_id,
                },
            )
            return PreconditionFailureResult(
                result=ValidationResultType.PRECONDITION_FAILURE.value,
                validated_at=validated_at,
                input_identity=input_identity,
                precondition_failed="STALE_OBSERVATIONS",
                reason=reason,
                retriable=True,
            )

        # ------------------------------------------------------------------
        # Category 7 — Relationship Validation
        # Contract §6 Category 7, Rule 7.9:
        #   All entity references resolved within the input context only.
        #   No external calls.
        # Also enforces Rule 7.10: duplicate source observations → INVALID.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.RELATIONSHIP_VALIDATION.value},
        )
        errors = self._validate_relationships(input_context)
        if errors:
            return self._make_invalid(
                validated_at, input_identity,
                ValidationCategory.RELATIONSHIP_VALIDATION, errors,
            )

        # ------------------------------------------------------------------
        # Category 8 — Comparison Eligibility Precondition
        # Contract §6 Category 8, §5.6:
        #   At least two observations from at least two distinct valid sources.
        #   Failure is PRECONDITION_FAILURE (not INVALID) — the input may be
        #   structurally correct but structurally insufficient for detection.
        # ------------------------------------------------------------------
        logger.debug(
            "validation_category_start",
            extra={"category": ValidationCategory.COMPARISON_ELIGIBILITY.value},
        )
        eligibility_failure = self._validate_comparison_eligibility(input_context)
        if eligibility_failure is not None:
            precondition_failed, reason = eligibility_failure
            logger.warning(
                "validation_precondition_failure",
                extra={
                    "category": ValidationCategory.COMPARISON_ELIGIBILITY.value,
                    "precondition_failed": precondition_failed,
                    "retriable": True,
                    "pipeline_execution_id": self._context.pipeline_execution_id,
                },
            )
            return PreconditionFailureResult(
                result=ValidationResultType.PRECONDITION_FAILURE.value,
                validated_at=validated_at,
                input_identity=input_identity,
                precondition_failed=precondition_failed,
                reason=reason,
                retriable=True,
            )

        # ------------------------------------------------------------------
        # All eight categories passed → VALID
        # ------------------------------------------------------------------
        observations: list[dict] = input_context.get("observations", [])
        distinct_sources: set[str] = {
            obs["source"]
            for obs in observations
            if isinstance(obs, dict) and isinstance(obs.get("source"), str)
        }

        logger.info(
            "validation_end",
            extra={
                "result": ValidationResultType.VALID.value,
                "input_identity": input_identity,
                "observation_count": len(observations),
                "source_count": len(distinct_sources),
                "pipeline_execution_id": self._context.pipeline_execution_id,
            },
        )
        return ValidResult(
            result=ValidationResultType.VALID.value,
            validated_at=validated_at,
            input_identity=input_identity,
            observation_count=len(observations),
            source_count=len(distinct_sources),
        )

    # ------------------------------------------------------------------
    # Category 1 — Schema Validation
    # ------------------------------------------------------------------

    def _validate_schema(self, input_context: Any) -> list[ValidationError]:
        """
        Contract §6 Category 1: the input must be a well-formed dict with the
        expected top-level keys. A non-dict or structurally unparseable input
        is a VALIDATION_FAILURE before any field-level checks occur.
        """
        errors: list[ValidationError] = []

        if not isinstance(input_context, dict):
            errors.append(ValidationError(
                field="<input_context>",
                received_value=type(input_context).__name__,
                reason=(
                    "The pipeline input context must be a structured dict. "
                    f"Received {type(input_context).__name__}."
                ),
                rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
            ))
            # Cannot continue checking top-level keys on a non-dict.
            return errors

        # Top-level required keys
        for key in sorted(self._REQUIRED_TOP_LEVEL_KEYS):  # sorted for deterministic order
            if key not in input_context:
                errors.append(ValidationError(
                    field=key,
                    received_value=None,
                    reason=f"Required top-level key '{key}' is absent from the input context.",
                    rule_violated=ValidationRule.NO_INFERENCE_OF_MISSING_VALUES.value,
                ))

        # listings and observations must be lists if present
        if "listings" in input_context and not isinstance(input_context["listings"], list):
            errors.append(ValidationError(
                field="listings",
                received_value=type(input_context["listings"]).__name__,
                reason=(
                    f"'listings' must be a list. "
                    f"Received {type(input_context['listings']).__name__}."
                ),
                rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
            ))
        if "observations" in input_context and not isinstance(input_context["observations"], list):
            errors.append(ValidationError(
                field="observations",
                received_value=type(input_context["observations"]).__name__,
                reason=(
                    f"'observations' must be a list. "
                    f"Received {type(input_context['observations']).__name__}."
                ),
                rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
            ))

        return errors

    # ------------------------------------------------------------------
    # Category 2 — Required Field Validation
    # ------------------------------------------------------------------

    def _validate_required_fields(self, input_context: dict) -> list[ValidationError]:
        """
        Contract §6 Category 2, §5: every required field must be present and non-null.
        Absence or null is a VALIDATION_FAILURE per Rule 7.3 (no inference of missing values).
        """
        errors: list[ValidationError] = []

        # --- Product (Contract §5.1) ---
        errors.extend(self._require_present(input_context, "product_id"))

        # At least one of product_name or external_id must be present and truthy
        has_name = bool(input_context.get("product_name"))
        has_ext_id = bool(input_context.get("external_id"))
        if not has_name and not has_ext_id:
            errors.append(ValidationError(
                field="product_name / external_id",
                received_value=None,
                reason=(
                    "At least one of 'product_name' or 'external_id' must be present "
                    "and non-empty. Both are absent or empty."
                ),
                rule_violated=ValidationRule.NO_INFERENCE_OF_MISSING_VALUES.value,
            ))

        # --- Rule sets and threshold (Contract §5.4) ---
        for f in ("discrepancy_rule_set", "scoring_factor_set", "alert_threshold"):
            errors.extend(self._require_present(input_context, f))

        # --- Listings (Contract §5.2) ---
        for idx, listing in enumerate(input_context.get("listings", [])):
            if not isinstance(listing, dict):
                errors.append(ValidationError(
                    field=f"listings[{idx}]",
                    received_value=type(listing).__name__,
                    reason=f"Each entry in 'listings' must be a dict. Index {idx} is not.",
                    rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
                ))
                continue
            for f in self._REQUIRED_LISTING_FIELDS:
                errors.extend(self._require_present(listing, f, prefix=f"listings[{idx}]."))

        # --- Observations (Contract §5.3) ---
        for idx, obs in enumerate(input_context.get("observations", [])):
            if not isinstance(obs, dict):
                errors.append(ValidationError(
                    field=f"observations[{idx}]",
                    received_value=type(obs).__name__,
                    reason=f"Each entry in 'observations' must be a dict. Index {idx} is not.",
                    rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
                ))
                continue
            for f in self._REQUIRED_OBSERVATION_FIELDS:
                errors.extend(self._require_present(obs, f, prefix=f"observations[{idx}]."))

        return errors

    # ------------------------------------------------------------------
    # Category 3 — Type Validation
    # ------------------------------------------------------------------

    def _validate_types(self, input_context: dict) -> list[ValidationError]:
        """
        Contract §6 Category 3: every field must be the correct type.
        Rule 7.2: a string that looks like a number is not a number.
                  A bool (Python subclass of int) is not an acceptable numeric value.
        """
        errors: list[ValidationError] = []

        errors.extend(self._check_type(input_context, "product_id", str))
        errors.extend(self._check_type(input_context, "discrepancy_rule_set", dict))
        errors.extend(self._check_type(input_context, "scoring_factor_set", dict))
        errors.extend(self._check_numeric_type(input_context, "alert_threshold"))

        for idx, listing in enumerate(input_context.get("listings", [])):
            if not isinstance(listing, dict):
                continue  # already flagged in Category 2
            p = f"listings[{idx}]."
            errors.extend(self._check_type(listing, "listing_id", str, prefix=p))
            errors.extend(self._check_type(listing, "source", str, prefix=p))
            errors.extend(self._check_type(listing, "external_id", str, prefix=p))
            errors.extend(self._check_type(listing, "product_ref", str, prefix=p))
            errors.extend(self._check_numeric_type(listing, "price", prefix=p))

        for idx, obs in enumerate(input_context.get("observations", [])):
            if not isinstance(obs, dict):
                continue  # already flagged in Category 2
            p = f"observations[{idx}]."
            errors.extend(self._check_type(obs, "observation_id", str, prefix=p))
            errors.extend(self._check_type(obs, "listing_ref", str, prefix=p))
            errors.extend(self._check_type(obs, "source", str, prefix=p))
            errors.extend(self._check_numeric_type(obs, "observed_price", prefix=p))
            # observed_at arrives as a string (ISO 8601) or as a datetime object.
            # Actual datetime parsing is performed in Category 6.
            val = obs.get("observed_at")
            if val is not None and not isinstance(val, (str, datetime)):
                errors.append(ValidationError(
                    field=f"{p}observed_at",
                    received_value=type(val).__name__,
                    reason=(
                        f"'observed_at' must be an ISO 8601 string or a datetime object. "
                        f"Received {type(val).__name__}."
                    ),
                    rule_violated=ValidationRule.NO_SILENT_COERCION.value,
                ))

        return errors

    # ------------------------------------------------------------------
    # Category 4 — Value Validation
    # ------------------------------------------------------------------

    def _validate_values(self, input_context: dict) -> list[ValidationError]:
        """
        Contract §6 Category 4: all values must meet their allowed constraints.
        Rule 7.6: price and observed_price must be strictly greater than zero.
                  Zero, negative, and null are all invalid.
        """
        errors: list[ValidationError] = []

        errors.extend(self._check_non_empty_string(input_context, "product_id"))
        errors.extend(self._check_strictly_positive(input_context, "alert_threshold"))

        # Rule sets must be non-empty dicts (Contract §5.4)
        for f in ("discrepancy_rule_set", "scoring_factor_set"):
            val = input_context.get(f)
            if isinstance(val, dict) and len(val) == 0:
                errors.append(ValidationError(
                    field=f,
                    received_value="{}",
                    reason=(
                        f"'{f}' must be a non-empty configuration object. "
                        "An empty dict carries no rules and cannot be used for evaluation."
                    ),
                    rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
                ))

        for idx, listing in enumerate(input_context.get("listings", [])):
            if not isinstance(listing, dict):
                continue
            p = f"listings[{idx}]."
            errors.extend(self._check_non_empty_string(listing, "listing_id", prefix=p))
            errors.extend(self._check_non_empty_string(listing, "source", prefix=p))
            errors.extend(self._check_non_empty_string(listing, "external_id", prefix=p))
            errors.extend(self._check_non_empty_string(listing, "product_ref", prefix=p))
            errors.extend(self._check_strictly_positive(listing, "price", prefix=p))

        for idx, obs in enumerate(input_context.get("observations", [])):
            if not isinstance(obs, dict):
                continue
            p = f"observations[{idx}]."
            errors.extend(self._check_non_empty_string(obs, "observation_id", prefix=p))
            errors.extend(self._check_non_empty_string(obs, "listing_ref", prefix=p))
            errors.extend(self._check_non_empty_string(obs, "source", prefix=p))
            errors.extend(self._check_strictly_positive(obs, "observed_price", prefix=p))
            # observed_at non-empty string (if it is a string)
            val = obs.get("observed_at")
            if isinstance(val, str) and not val.strip():
                errors.append(ValidationError(
                    field=f"{p}observed_at",
                    received_value="<empty string>",
                    reason=(
                        f"'{p}observed_at' must not be an empty or whitespace-only string."
                    ),
                    rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
                ))

        return errors

    # ------------------------------------------------------------------
    # Category 5 — Source Validation
    # ------------------------------------------------------------------

    def _validate_sources(self, input_context: dict) -> list[ValidationError]:
        """
        Contract §6 Category 5, Rule 7.7:
        Every source identifier must be non-empty and belong to the spec-defined
        allowed source set. An unrecognised source is invalid even if non-empty.

        The allowed source set is provided via ValidationContext.allowed_sources —
        the validator does not derive it from any external system.
        """
        errors: list[ValidationError] = []

        for idx, listing in enumerate(input_context.get("listings", [])):
            if not isinstance(listing, dict):
                continue
            source = listing.get("source")
            if isinstance(source, str) and source and source not in self._context.allowed_sources:
                errors.append(ValidationError(
                    field=f"listings[{idx}].source",
                    received_value=source,
                    reason=(
                        f"Source '{source}' is not in the allowed source set. "
                        "Only spec-defined source identifiers are accepted."
                    ),
                    rule_violated=ValidationRule.SOURCE_MUST_BE_RECOGNIZED.value,
                ))

        for idx, obs in enumerate(input_context.get("observations", [])):
            if not isinstance(obs, dict):
                continue
            source = obs.get("source")
            if isinstance(source, str) and source and source not in self._context.allowed_sources:
                errors.append(ValidationError(
                    field=f"observations[{idx}].source",
                    received_value=source,
                    reason=(
                        f"Source '{source}' is not in the allowed source set. "
                        "Only spec-defined source identifiers are accepted."
                    ),
                    rule_violated=ValidationRule.SOURCE_MUST_BE_RECOGNIZED.value,
                ))

        return errors

    # ------------------------------------------------------------------
    # Category 6 — Timestamp Validation
    # ------------------------------------------------------------------

    def _validate_timestamps(
        self,
        input_context: dict,
    ) -> tuple[list[ValidationError], list[str]]:
        """
        Contract §6 Category 6, Rule 7.8.

        Two-pass check applied to every observation timestamp:

        Pass 1 — Format check:
            Confirm observed_at is a parseable ISO 8601 datetime with timezone
            information. A malformed timestamp → INVALID (caller converts to
            InvalidResult). Returns all format errors collected across all
            observations before returning.

        Pass 2 — Freshness check (only if pass 1 produced no errors):
            Confirm each parsed timestamp falls within the freshness window.
            age = freshness_reference_timestamp - observed_at
            if age > freshness_window_seconds → stale.
            Stale observations → PRECONDITION_FAILURE (caller converts).

        The freshness_reference_timestamp from ValidationContext is used
        exclusively. The system clock is never read (Contract §10 Rule 3).

        Returns
        -------
        (format_errors, stale_observation_ids):
            Exactly one of the two will be non-empty at a time.
            format_errors:          list of ValidationError (→ INVALID)
            stale_observation_ids:  list of observation_id strings (→ PRECONDITION_FAILURE)
        """
        format_errors: list[ValidationError] = []
        stale_ids: list[str] = []

        reference = self._context.freshness_reference_timestamp
        window_seconds = self._context.freshness_window_seconds

        for idx, obs in enumerate(input_context.get("observations", [])):
            if not isinstance(obs, dict):
                continue
            raw_ts = obs.get("observed_at")
            if raw_ts is None:
                continue  # already caught in required-field check

            # --- Parse ---
            if isinstance(raw_ts, datetime):
                # Accept pre-parsed datetime objects from Python callers.
                # Require timezone info for unambiguous comparison.
                if raw_ts.tzinfo is None:
                    obs_id = obs.get("observation_id", f"<index {idx}>")
                    format_errors.append(ValidationError(
                        field=f"observations[{idx}].observed_at",
                        received_value="<naive datetime>",
                        reason=(
                            "Datetime objects passed as observed_at must be timezone-aware. "
                            "A naive datetime cannot be unambiguously compared to the "
                            "freshness reference timestamp."
                        ),
                        rule_violated=ValidationRule.FRESHNESS_IS_MANDATORY.value,
                    ))
                    continue
                parsed: datetime = raw_ts
            elif isinstance(raw_ts, str):
                parsed = self._parse_iso8601(raw_ts)
                if parsed is None:
                    format_errors.append(ValidationError(
                        field=f"observations[{idx}].observed_at",
                        received_value=raw_ts,
                        reason=(
                            f"'{raw_ts}' is not a valid ISO 8601 datetime string with "
                            "timezone information. Timestamps must be well-formed ISO 8601 "
                            "values (e.g. '2026-04-13T10:00:00+00:00')."
                        ),
                        rule_violated=ValidationRule.NO_SILENT_COERCION.value,
                    ))
                    continue
            else:
                continue  # wrong type already caught in Category 3

            # --- Freshness check (pass 2) —
            # Only reached if this observation's timestamp parsed successfully.
            # Use freshness_reference_timestamp exclusively (Rule 7.8, §10 Rule 3).
            age_seconds = (reference - parsed).total_seconds()
            if age_seconds > window_seconds:
                obs_id = obs.get("observation_id", f"<index {idx}>")
                stale_ids.append(obs_id)

        # If any format errors exist, return them as INVALID.
        # Do not surface staleness alongside format errors.
        if format_errors:
            return format_errors, []
        return [], stale_ids

    # ------------------------------------------------------------------
    # Category 7 — Relationship Validation
    # ------------------------------------------------------------------

    def _validate_relationships(self, input_context: dict) -> list[ValidationError]:
        """
        Contract §6 Category 7, Rule 7.9:
        All entity references must resolve within the input context itself.
        No external calls are made.

        Checks:
          1. Every listing.product_ref must equal the product_id in context.
          2. Every observation.listing_ref must reference a listing_id in context.
          3. Every observation.source must match its referenced listing's source.
          4. No two observations may share the same source for the same product
             (Rule 7.10 — duplicate source observations → VALIDATION_FAILURE).

        Error ordering is deterministic: listings are checked before observations;
        within each, indices are checked in ascending order.
        """
        errors: list[ValidationError] = []
        product_id: str = input_context.get("product_id", "")

        # Build a listing_id → listing dict for O(1) reference lookups.
        # Iteration order of the input list is preserved for deterministic checks.
        listing_map: dict[str, dict] = {}
        for idx, listing in enumerate(input_context.get("listings", [])):
            if not isinstance(listing, dict):
                continue

            # Check 1: listing must reference the product in this context.
            product_ref = listing.get("product_ref")
            if (
                isinstance(product_ref, str)
                and product_ref
                and product_ref != product_id
            ):
                errors.append(ValidationError(
                    field=f"listings[{idx}].product_ref",
                    received_value=product_ref,
                    reason=(
                        f"listings[{idx}].product_ref '{product_ref}' does not match "
                        f"the product_id '{product_id}' in this input context."
                    ),
                    rule_violated=ValidationRule.RELATIONSHIPS_WITHIN_CONTEXT.value,
                ))

            lid = listing.get("listing_id")
            if isinstance(lid, str) and lid:
                listing_map[lid] = listing

        # Observation checks — process in index order for determinism.
        # sources_seen tracks distinct sources encountered; duplicate detection
        # uses a set to avoid emitting more than one error per duplicate source.
        sources_seen: list[str] = []        # ordered, for deterministic duplicate detection
        reported_duplicate_sources: set[str] = set()

        for idx, obs in enumerate(input_context.get("observations", [])):
            if not isinstance(obs, dict):
                continue

            listing_ref = obs.get("listing_ref")
            obs_source = obs.get("source")

            # Check 2: observation must reference a listing that exists in context.
            if isinstance(listing_ref, str) and listing_ref:
                if listing_ref not in listing_map:
                    errors.append(ValidationError(
                        field=f"observations[{idx}].listing_ref",
                        received_value=listing_ref,
                        reason=(
                            f"observations[{idx}].listing_ref '{listing_ref}' does not "
                            "reference any listing_id present in this input context. "
                            "Orphan observation detected."
                        ),
                        rule_violated=ValidationRule.RELATIONSHIPS_WITHIN_CONTEXT.value,
                    ))
                else:
                    # Check 3: observation source must match its referenced listing's source.
                    referenced_listing = listing_map[listing_ref]
                    listing_source = referenced_listing.get("source")
                    if (
                        isinstance(obs_source, str)
                        and isinstance(listing_source, str)
                        and obs_source != listing_source
                    ):
                        errors.append(ValidationError(
                            field=f"observations[{idx}].source",
                            received_value=obs_source,
                            reason=(
                                f"observations[{idx}].source '{obs_source}' does not match "
                                f"the source '{listing_source}' of the referenced listing "
                                f"'{listing_ref}'."
                            ),
                            rule_violated=ValidationRule.RELATIONSHIPS_WITHIN_CONTEXT.value,
                        ))

            # Check 4: Rule 7.10 — duplicate source per product → VALIDATION_FAILURE.
            # Each source may appear in at most one observation for the same product.
            if isinstance(obs_source, str) and obs_source:
                if obs_source in sources_seen:
                    # Only emit one error per duplicate source (not one per extra occurrence).
                    if obs_source not in reported_duplicate_sources:
                        reported_duplicate_sources.add(obs_source)
                        errors.append(ValidationError(
                            field=f"observations[{idx}].source",
                            received_value=obs_source,
                            reason=(
                                f"More than one observation references source '{obs_source}' "
                                "for the same product. Only one observation per source per "
                                "product is permitted as input to the comparison pipeline "
                                "(Rule 7.10)."
                            ),
                            rule_violated=ValidationRule.NO_DUPLICATE_SOURCE_OBSERVATIONS.value,
                        ))
                else:
                    sources_seen.append(obs_source)

        return errors

    # ------------------------------------------------------------------
    # Category 8 — Comparison Eligibility Precondition
    # ------------------------------------------------------------------

    def _validate_comparison_eligibility(
        self,
        input_context: dict,
    ) -> tuple[str, str] | None:
        """
        Contract §6 Category 8, §5.6:
        The input must contain at least two observations from at least two
        distinct valid sources for the same product.

        This is a PRECONDITION_FAILURE — not an INVALID — because the input may
        be individually correct but structurally insufficient for the pipeline.
        The pipeline cannot detect a discrepancy with fewer than two sources.

        Returns
        -------
        None if the precondition is satisfied.
        (precondition_failed: str, reason: str) if not satisfied.
        """
        observations = input_context.get("observations", [])

        # Only count observations that passed earlier categories (have a non-empty source).
        valid_obs = [
            obs for obs in observations
            if isinstance(obs, dict)
            and isinstance(obs.get("source"), str)
            and obs.get("source")
        ]
        distinct_sources = {obs["source"] for obs in valid_obs}

        if len(distinct_sources) < 2:
            return (
                "INSUFFICIENT_DISTINCT_SOURCES",
                (
                    f"The input contains {len(distinct_sources)} distinct valid source(s) "
                    f"across {len(valid_obs)} observation(s). "
                    "At least two observations from at least two distinct valid sources "
                    "are required for the discrepancy detection stage to execute."
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Private helpers — result construction
    # ------------------------------------------------------------------

    def _make_invalid(
        self,
        validated_at: datetime,
        input_identity: str,
        category: ValidationCategory,
        errors: list[ValidationError],
    ) -> InvalidResult:
        """Construct an InvalidResult and emit the required structured log entry."""
        logger.warning(
            "validation_end",
            extra={
                "result": ValidationResultType.INVALID.value,
                "failure_category": category.value,
                "failing_fields": [e.field for e in errors],
                "error_count": len(errors),
                "pipeline_execution_id": self._context.pipeline_execution_id,
            },
        )
        return InvalidResult(
            result=ValidationResultType.INVALID.value,
            validated_at=validated_at,
            input_identity=input_identity,
            failure_category=category.value,
            errors=tuple(errors),
        )

    def _extract_input_identity(self, input_context: Any) -> str:
        """
        Extract a stable identity string from the input context.

        The product_id is used as the identity because it is the most stable
        identifier for the input data itself. The validator must not infer or
        generate an identity if product_id is absent.
        """
        if isinstance(input_context, dict):
            product_id = input_context.get("product_id")
            if isinstance(product_id, str) and product_id:
                return product_id
        return "<unknown>"

    # ------------------------------------------------------------------
    # Private helpers — field-level checks
    # ------------------------------------------------------------------

    def _require_present(
        self,
        obj: dict,
        field_name: str,
        prefix: str = "",
    ) -> list[ValidationError]:
        """
        Return a ValidationError if obj[field_name] is absent or None.
        Rule 7.3: the validator must not infer or default a missing value.
        """
        if field_name not in obj or obj[field_name] is None:
            return [ValidationError(
                field=f"{prefix}{field_name}",
                received_value=None,
                reason=f"Required field '{prefix}{field_name}' is absent or null.",
                rule_violated=ValidationRule.NO_INFERENCE_OF_MISSING_VALUES.value,
            )]
        return []

    def _check_type(
        self,
        obj: dict,
        field_name: str,
        expected_type: type,
        prefix: str = "",
    ) -> list[ValidationError]:
        """
        Return a ValidationError if obj[field_name] is not an instance of
        expected_type. Skips None values (already caught in required-field check).

        Note: bool is a subclass of int in Python. This method rejects bool for
        any expected_type that is int or float.
        """
        val = obj.get(field_name)
        if val is None:
            return []
        if isinstance(val, bool) and expected_type in (int, float):
            return [ValidationError(
                field=f"{prefix}{field_name}",
                received_value=type(val).__name__,
                reason=(
                    f"'{prefix}{field_name}' must be {expected_type.__name__}, "
                    "not bool. A boolean is not an acceptable numeric value."
                ),
                rule_violated=ValidationRule.NO_SILENT_COERCION.value,
            )]
        if not isinstance(val, expected_type):
            return [ValidationError(
                field=f"{prefix}{field_name}",
                received_value=type(val).__name__,
                reason=(
                    f"'{prefix}{field_name}' must be of type {expected_type.__name__}. "
                    f"Received {type(val).__name__}."
                ),
                rule_violated=ValidationRule.NO_SILENT_COERCION.value,
            )]
        return []

    def _check_numeric_type(
        self,
        obj: dict,
        field_name: str,
        prefix: str = "",
    ) -> list[ValidationError]:
        """
        Return a ValidationError if obj[field_name] is not int or float.
        Rule 7.2: a string that looks like a number is not a number.
        bool is rejected because isinstance(True, int) is True in Python.
        """
        val = obj.get(field_name)
        if val is None:
            return []
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return [ValidationError(
                field=f"{prefix}{field_name}",
                received_value=type(val).__name__,
                reason=(
                    f"'{prefix}{field_name}' must be a numeric value (int or float). "
                    f"Received {type(val).__name__}. "
                    "A string that looks like a number is not a number (Rule 7.2)."
                ),
                rule_violated=ValidationRule.NO_SILENT_COERCION.value,
            )]
        return []

    def _check_non_empty_string(
        self,
        obj: dict,
        field_name: str,
        prefix: str = "",
    ) -> list[ValidationError]:
        """
        Return a ValidationError if obj[field_name] is a whitespace-only string.
        Skips None (caught in required-field check) and non-strings (caught in type check).
        The validator does not strip whitespace — it checks as-received (Rule 7.2).
        """
        val = obj.get(field_name)
        if val is None or not isinstance(val, str):
            return []
        if not val.strip():
            return [ValidationError(
                field=f"{prefix}{field_name}",
                received_value="<empty string>",
                reason=(
                    f"'{prefix}{field_name}' must be a non-empty string. "
                    "An empty or whitespace-only value is not acceptable."
                ),
                rule_violated=ValidationRule.NO_SILENT_ACCEPTANCE.value,
            )]
        return []

    def _check_strictly_positive(
        self,
        obj: dict,
        field_name: str,
        prefix: str = "",
    ) -> list[ValidationError]:
        """
        Rule 7.6: the value must be strictly greater than zero.
        Zero, negative values, and null are all invalid.
        Skips non-numeric values (caught in type check).
        """
        val = obj.get(field_name)
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return []
        if val <= 0:
            return [ValidationError(
                field=f"{prefix}{field_name}",
                received_value=val,
                reason=(
                    f"'{prefix}{field_name}' must be strictly greater than zero. "
                    f"Received {val}. Zero and negative values are not valid (Rule 7.6)."
                ),
                rule_violated=ValidationRule.PRICE_STRICTLY_POSITIVE.value,
            )]
        return []

    @staticmethod
    def _parse_iso8601(value: str) -> datetime | None:
        """
        Parse value as an ISO 8601 datetime string.

        Returns a timezone-aware datetime on success, or None on failure.

        Requires timezone information. A naive datetime string (no UTC offset or Z)
        returns None — it cannot be unambiguously compared to a reference timestamp.

        Rule 7.2: A string that looks like a datetime is not a datetime unless it
        parses correctly per the defined format. No coercion, no guessing.
        """
        try:
            dt = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is None:
            return None
        return dt
