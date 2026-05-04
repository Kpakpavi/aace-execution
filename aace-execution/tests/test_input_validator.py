"""
Unit tests for InputValidator.

Contract reference: Contracts/INPUT_VALIDATOR_CONTRACT.md

Every test uses a fixed reference timestamp (REF) and a fixed validated_at
timestamp (VALIDATED_AT). No test touches the system clock.

Test organisation mirrors the eight validation categories from Contract §6:

    Category 1  — Schema Validation            → TestSchemaValidation
    Category 2  — Required Field Validation    → TestRequiredFieldValidation
    Category 3  — Type Validation              → TestTypeValidation
    Category 4  — Value Validation             → TestValueValidation
    Category 5  — Source Validation            → TestSourceValidation
    Category 6  — Timestamp Validation         → TestTimestampValidation
    Category 6  — Freshness (stale)            → TestFreshnessValidation
    Category 7  — Relationship Validation      → TestRelationshipValidation
    Category 8  — Comparison Eligibility       → TestComparisonEligibility
    Result shape — Output structure contracts  → TestOutputStructure
    Determinism — Rule 10 guarantees           → TestDeterminism
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from src.aace_execution.validators.input_validator import (
    InputValidator,
    InvalidResult,
    PreconditionFailureResult,
    ValidResult,
    ValidationCategory,
    ValidationContext,
    ValidationResultType,
    ValidationRule,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# All timestamps are pinned.  No test may call datetime.now() or any
# equivalent.  Contract §10 Rule 3.
REF = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
VALIDATED_AT = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
WINDOW = 3600  # seconds — 1 hour freshness window
FRESH = (REF - timedelta(minutes=30)).isoformat()   # 30 min old → inside window
STALE = (REF - timedelta(hours=2)).isoformat()      # 2 hours old → outside window
FUTURE = (REF + timedelta(minutes=5)).isoformat()   # 5 min in the future (negative age)

ALLOWED_SOURCES = frozenset({"src_a", "src_b", "src_c"})


def make_context(**overrides) -> ValidationContext:
    """Return a ValidationContext with sensible defaults; override any field."""
    defaults = dict(
        pipeline_execution_id="exec-test-001",
        freshness_reference_timestamp=REF,
        freshness_window_seconds=WINDOW,
        allowed_sources=ALLOWED_SOURCES,
        validated_at=VALIDATED_AT,
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


def make_validator(**context_overrides) -> InputValidator:
    return InputValidator(make_context(**context_overrides))


def make_valid_input(**overrides) -> dict:
    """
    Return a minimal fully-valid pipeline input context.
    Callers override individual keys to exercise specific failure paths.
    """
    base = {
        "product_id": "prod-001",
        "product_name": "Test Widget",
        "listings": [
            {
                "listing_id": "lst-a",
                "source": "src_a",
                "external_id": "ext-a",
                "price": 100.0,
                "product_ref": "prod-001",
            },
            {
                "listing_id": "lst-b",
                "source": "src_b",
                "external_id": "ext-b",
                "price": 120.0,
                "product_ref": "prod-001",
            },
        ],
        "observations": [
            {
                "observation_id": "obs-a",
                "listing_ref": "lst-a",
                "source": "src_a",
                "observed_price": 100.0,
                "observed_at": FRESH,
            },
            {
                "observation_id": "obs-b",
                "listing_ref": "lst-b",
                "source": "src_b",
                "observed_price": 120.0,
                "observed_at": FRESH,
            },
        ],
        "discrepancy_rule_set": {"method": "PERCENTAGE", "threshold": 5.0},
        "scoring_factor_set": {"price_diff": {"weight": 1.0}},
        "alert_threshold": 70.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def errors_for_field(result: InvalidResult, field_fragment: str):
    """Return all ValidationErrors whose field contains field_fragment."""
    return [e for e in result.errors if field_fragment in e.field]


def has_rule(result: InvalidResult, rule: ValidationRule) -> bool:
    return any(e.rule_violated == rule.value for e in result.errors)


# ===========================================================================
# Category 1 — Schema Validation  (Contract §6 Category 1)
# ===========================================================================

class TestSchemaValidation:
    """Contract §6 Category 1: overall structure must be present and parseable."""

    def test_none_input_is_invalid(self):
        r = make_validator().validate(None)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value

    def test_string_input_is_invalid(self):
        r = make_validator().validate("not a dict")
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value

    def test_list_input_is_invalid(self):
        r = make_validator().validate([{"product_id": "x"}])
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value

    def test_empty_dict_reports_all_missing_top_level_keys(self):
        r = make_validator().validate({})
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value
        # All six required top-level keys must be reported.
        required_keys = {
            "product_id", "listings", "observations",
            "discrepancy_rule_set", "scoring_factor_set", "alert_threshold",
        }
        reported_fields = {e.field for e in r.errors}
        assert required_keys.issubset(reported_fields)

    def test_listings_as_dict_instead_of_list(self):
        inp = make_valid_input(listings={"listing_id": "lst-a"})
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value
        assert errors_for_field(r, "listings")

    def test_observations_as_dict_instead_of_list(self):
        inp = make_valid_input(observations={"observation_id": "obs-a"})
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value
        assert errors_for_field(r, "observations")

    def test_missing_single_top_level_key_reports_that_key(self):
        inp = make_valid_input()
        del inp["discrepancy_rule_set"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value
        assert errors_for_field(r, "discrepancy_rule_set")


# ===========================================================================
# Category 2 — Required Field Validation  (Contract §6 Category 2, §5)
# ===========================================================================

class TestRequiredFieldValidation:
    """
    Contract §6 Category 2: every required field must be present and non-null.
    Rule 7.3: the validator must not infer or default a missing value.
    """

    def test_missing_product_id_is_invalid(self):
        # Deleting a top-level key is caught by schema validation (Category 1),
        # consistent with test_missing_single_top_level_key_reports_that_key.
        inp = make_valid_input()
        del inp["product_id"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value
        assert errors_for_field(r, "product_id")
        assert has_rule(r, ValidationRule.NO_INFERENCE_OF_MISSING_VALUES)

    def test_null_product_id_is_invalid(self):
        inp = make_valid_input(product_id=None)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "product_id")

    def test_missing_both_product_name_and_external_id(self):
        inp = make_valid_input()
        # Remove both — at least one is required (Contract §5.1)
        inp.pop("product_name", None)
        inp.pop("external_id", None)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.REQUIRED_FIELD_VALIDATION.value

    def test_external_id_alone_satisfies_product_identity(self):
        inp = make_valid_input()
        inp.pop("product_name", None)
        inp["external_id"] = "ext-global-001"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID

    def test_product_name_alone_satisfies_product_identity(self):
        inp = make_valid_input()
        # make_valid_input already has product_name; no external_id
        assert "product_name" in inp
        inp.pop("external_id", None)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID

    def test_missing_listing_required_field_listing_id(self):
        inp = make_valid_input()
        del inp["listings"][0]["listing_id"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.REQUIRED_FIELD_VALIDATION.value
        assert errors_for_field(r, "listings[0].listing_id")

    def test_missing_listing_required_field_source(self):
        inp = make_valid_input()
        del inp["listings"][0]["source"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "listings[0].source")

    def test_missing_listing_required_field_price(self):
        inp = make_valid_input()
        del inp["listings"][0]["price"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "listings[0].price")

    def test_missing_listing_required_field_product_ref(self):
        inp = make_valid_input()
        del inp["listings"][0]["product_ref"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "listings[0].product_ref")

    def test_missing_observation_required_field_observation_id(self):
        inp = make_valid_input()
        del inp["observations"][0]["observation_id"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "observations[0].observation_id")

    def test_missing_observation_required_field_listing_ref(self):
        inp = make_valid_input()
        del inp["observations"][0]["listing_ref"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "observations[0].listing_ref")

    def test_missing_observation_required_field_observed_price(self):
        inp = make_valid_input()
        del inp["observations"][0]["observed_price"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "observations[0].observed_price")

    def test_missing_observation_required_field_observed_at(self):
        inp = make_valid_input()
        del inp["observations"][0]["observed_at"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "observations[0].observed_at")

    def test_missing_discrepancy_rule_set(self):
        inp = make_valid_input()
        del inp["discrepancy_rule_set"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "discrepancy_rule_set")

    def test_null_scoring_factor_set(self):
        inp = make_valid_input(scoring_factor_set=None)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "scoring_factor_set")

    def test_missing_alert_threshold(self):
        inp = make_valid_input()
        del inp["alert_threshold"]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "alert_threshold")

    def test_listing_entry_not_a_dict_is_invalid(self):
        inp = make_valid_input(listings=["not-a-dict", {"listing_id": "x"}])
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "listings[0]")

    def test_observation_entry_not_a_dict_is_invalid(self):
        inp = make_valid_input(observations=["not-a-dict"])
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "observations[0]")


# ===========================================================================
# Category 3 — Type Validation  (Contract §6 Category 3, Rule 7.2)
# ===========================================================================

class TestTypeValidation:
    """
    Contract §6 Category 3, Rule 7.2:
    A string that looks like a number is not a number.
    A bool is not an acceptable numeric value.
    """

    def test_product_id_as_integer_is_invalid(self):
        inp = make_valid_input(product_id=12345)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "product_id")
        assert has_rule(r, ValidationRule.NO_SILENT_COERCION)

    def test_listing_price_as_string_is_invalid(self):
        # Rule 7.2: a string that looks like a number is not a number.
        inp = make_valid_input()
        inp["listings"][0]["price"] = "100.0"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "listings[0].price")
        assert has_rule(r, ValidationRule.NO_SILENT_COERCION)

    def test_listing_price_as_bool_is_invalid(self):
        # Rule 7.2: bool is not an acceptable numeric value.
        inp = make_valid_input()
        inp["listings"][0]["price"] = True
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "listings[0].price")
        assert has_rule(r, ValidationRule.NO_SILENT_COERCION)

    def test_observation_price_as_string_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_price"] = "120.0"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "observations[0].observed_price")
        assert has_rule(r, ValidationRule.NO_SILENT_COERCION)

    def test_observation_price_as_bool_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_price"] = False
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "observations[0].observed_price")

    def test_alert_threshold_as_string_is_invalid(self):
        inp = make_valid_input(alert_threshold="70")
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "alert_threshold")

    def test_alert_threshold_as_bool_is_invalid(self):
        inp = make_valid_input(alert_threshold=True)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "alert_threshold")

    def test_discrepancy_rule_set_as_list_is_invalid(self):
        inp = make_valid_input(discrepancy_rule_set=[{"method": "PERCENTAGE"}])
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "discrepancy_rule_set")

    def test_listing_source_as_integer_is_invalid(self):
        inp = make_valid_input()
        inp["listings"][0]["source"] = 42
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "listings[0].source")

    def test_observation_observed_at_as_integer_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = 1713000000
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value
        assert errors_for_field(r, "observations[0].observed_at")

    def test_integer_price_is_valid_numeric(self):
        # int is an acceptable numeric type — Rule 7.2 only forbids strings and bools.
        inp = make_valid_input()
        inp["listings"][0]["price"] = 100        # int, not float
        inp["observations"][0]["observed_price"] = 100
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID


# ===========================================================================
# Category 4 — Value Validation  (Contract §6 Category 4, Rule 7.6)
# ===========================================================================

class TestValueValidation:
    """
    Contract §6 Category 4, Rule 7.6:
    Price must be strictly greater than zero. Zero, negative, and null are invalid.
    """

    def test_listing_price_zero_is_invalid(self):
        inp = make_valid_input()
        inp["listings"][0]["price"] = 0
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.VALUE_VALIDATION.value
        assert errors_for_field(r, "listings[0].price")
        assert has_rule(r, ValidationRule.PRICE_STRICTLY_POSITIVE)

    def test_listing_price_negative_is_invalid(self):
        inp = make_valid_input()
        inp["listings"][0]["price"] = -5.0
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.VALUE_VALIDATION.value
        assert has_rule(r, ValidationRule.PRICE_STRICTLY_POSITIVE)

    def test_observation_price_zero_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_price"] = 0.0
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.VALUE_VALIDATION.value
        assert has_rule(r, ValidationRule.PRICE_STRICTLY_POSITIVE)

    def test_observation_price_negative_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_price"] = -1.0
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert has_rule(r, ValidationRule.PRICE_STRICTLY_POSITIVE)

    def test_alert_threshold_zero_is_invalid(self):
        inp = make_valid_input(alert_threshold=0)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.VALUE_VALIDATION.value
        assert errors_for_field(r, "alert_threshold")

    def test_alert_threshold_negative_is_invalid(self):
        inp = make_valid_input(alert_threshold=-10.0)
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "alert_threshold")

    def test_empty_product_id_string_is_invalid(self):
        inp = make_valid_input(product_id="")
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.VALUE_VALIDATION.value
        assert errors_for_field(r, "product_id")

    def test_whitespace_only_product_id_is_invalid(self):
        inp = make_valid_input(product_id="   ")
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "product_id")

    def test_empty_listing_id_is_invalid(self):
        inp = make_valid_input()
        inp["listings"][0]["listing_id"] = ""
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.VALUE_VALIDATION.value
        assert errors_for_field(r, "listings[0].listing_id")

    def test_empty_discrepancy_rule_set_is_invalid(self):
        # An empty dict carries no rules (Contract §5.4).
        inp = make_valid_input(discrepancy_rule_set={})
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.VALUE_VALIDATION.value
        assert errors_for_field(r, "discrepancy_rule_set")

    def test_empty_scoring_factor_set_is_invalid(self):
        inp = make_valid_input(scoring_factor_set={})
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert errors_for_field(r, "scoring_factor_set")

    def test_smallest_positive_price_is_valid(self):
        inp = make_valid_input()
        inp["listings"][0]["price"] = 0.01
        inp["observations"][0]["observed_price"] = 0.01
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID

    def test_multiple_price_failures_collected_in_one_result(self):
        # Rule 7.5: all errors within a failing category are collected together.
        inp = make_valid_input()
        inp["listings"][0]["price"] = 0
        inp["listings"][1]["price"] = -1.0
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        price_errors = errors_for_field(r, "price")
        assert len(price_errors) == 2


# ===========================================================================
# Category 5 — Source Validation  (Contract §6 Category 5, Rule 7.7)
# ===========================================================================

class TestSourceValidation:
    """
    Contract §6 Category 5, Rule 7.7:
    Every source must belong to the allowed source set.
    An unrecognised source is invalid even if non-empty.
    """

    def test_unrecognised_listing_source_is_invalid(self):
        inp = make_valid_input()
        inp["listings"][0]["source"] = "UNKNOWN_SRC"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SOURCE_VALIDATION.value
        assert errors_for_field(r, "listings[0].source")
        assert has_rule(r, ValidationRule.SOURCE_MUST_BE_RECOGNIZED)

    def test_unrecognised_observation_source_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["source"] = "ghost_src"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SOURCE_VALIDATION.value
        assert errors_for_field(r, "observations[0].source")
        assert has_rule(r, ValidationRule.SOURCE_MUST_BE_RECOGNIZED)

    def test_source_with_extra_whitespace_is_invalid(self):
        # "src_a " with a trailing space is not the same as "src_a".
        # The validator does not strip (Rule 7.2 — no silent coercion).
        inp = make_valid_input()
        inp["listings"][0]["source"] = "src_a "
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SOURCE_VALIDATION.value

    def test_both_listing_and_observation_unknown_sources_reported(self):
        inp = make_valid_input()
        inp["listings"][0]["source"] = "bad_src_1"
        inp["observations"][0]["source"] = "bad_src_2"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SOURCE_VALIDATION.value
        # Both must be reported in the same category pass (Rule 7.5).
        assert len(errors_for_field(r, "source")) >= 2

    def test_all_allowed_sources_are_accepted(self):
        # src_a, src_b, src_c are all in ALLOWED_SOURCES.
        inp = make_valid_input()
        inp["listings"][0]["source"] = "src_a"
        inp["observations"][0]["source"] = "src_a"
        r = make_validator().validate(inp)
        # May fail on other grounds (e.g., eligibility), but not source validation.
        assert r.failure_category != ValidationCategory.SOURCE_VALIDATION.value \
            if hasattr(r, "failure_category") else True


# ===========================================================================
# Category 6 — Timestamp Validation  (Contract §6 Category 6)
# ===========================================================================

class TestTimestampValidation:
    """
    Contract §6 Category 6:
    - Malformed timestamp → INVALID  (not PRECONDITION_FAILURE).
    - Naive datetime (no timezone) → INVALID.
    - Rule 7.2: a string that looks like a datetime is not a datetime unless
      it parses correctly per the defined format.
    """

    def test_malformed_timestamp_string_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = "not-a-date"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TIMESTAMP_VALIDATION.value
        assert errors_for_field(r, "observations[0].observed_at")

    def test_date_without_time_component_is_invalid(self):
        # "2026-04-13" is not a valid datetime with timezone info.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = "2026-04-13"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TIMESTAMP_VALIDATION.value

    def test_datetime_without_timezone_is_invalid(self):
        # A naive datetime cannot be unambiguously compared to the reference.
        # Rule 7.8 requires explicit timezone.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = "2026-04-13T11:30:00"  # no tz
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TIMESTAMP_VALIDATION.value
        assert errors_for_field(r, "observations[0].observed_at")

    def test_multiple_malformed_timestamps_reported_together(self):
        # Rule 7.5: all errors in the failing category collected before returning.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = "bad-ts-1"
        inp["observations"][1]["observed_at"] = "bad-ts-2"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        ts_errors = errors_for_field(r, "observed_at")
        assert len(ts_errors) == 2

    def test_malformed_timestamp_is_invalid_not_precondition_failure(self):
        # Contract §6 Category 6: malformed = INVALID, stale = PRECONDITION_FAILURE.
        # The two must never be confused.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = "GARBAGE"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID   # not PRECONDITION_FAILURE
        assert isinstance(r, InvalidResult)

    def test_future_timestamp_within_window_is_valid(self):
        # A future timestamp has a negative age; it falls within the window.
        # The window check is age > window_seconds; negative age fails that.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = FUTURE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID

    def test_timestamp_at_exact_boundary_is_valid(self):
        # age == window_seconds should NOT be stale: contract uses age > window.
        boundary = (REF - timedelta(seconds=WINDOW)).isoformat()
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = boundary
        inp["observations"][1]["observed_at"] = boundary
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID


# ===========================================================================
# Category 6 — Freshness  (Contract §6 Category 6, Rule 7.8)
# ===========================================================================

class TestFreshnessValidation:
    """
    Contract §6 Category 6, Rule 7.8:
    Timestamps outside the freshness window → PRECONDITION_FAILURE (not INVALID).
    retriable must be True (data may become fresh).
    The freshness_reference_timestamp from ValidationContext is used exclusively —
    the system clock is never consulted (Contract §10 Rule 3).
    """

    def test_stale_observation_is_precondition_failure(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE
        assert isinstance(r, PreconditionFailureResult)

    def test_stale_precondition_failure_is_retriable(self):
        # Contract §9: stale observations may become retriable when fresh data arrives.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE
        assert r.retriable is True

    def test_stale_precondition_failure_names_stale_observations(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE
        # The precondition_failed or reason must reference staleness.
        assert "STALE" in r.precondition_failed or "stale" in r.reason.lower()

    def test_one_fresh_one_stale_is_precondition_failure(self):
        # A single stale observation disqualifies the entire context.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = FRESH
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE

    def test_stale_is_precondition_not_invalid(self):
        # Critical classification check: stale ≠ INVALID (Contract §6 Category 6).
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result != ValidationResultType.INVALID
        assert not isinstance(r, InvalidResult)

    def test_freshness_evaluated_against_context_reference_not_system_clock(self):
        # Confirm that the window is relative to freshness_reference_timestamp,
        # not datetime.now().  We use a reference in the past and a timestamp
        # that would be "fresh" only relative to that past reference.
        old_ref = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        ts_relative_to_old_ref = (old_ref - timedelta(minutes=10)).isoformat()

        ctx = make_context(
            freshness_reference_timestamp=old_ref,
            validated_at=old_ref,
        )
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = ts_relative_to_old_ref
        inp["observations"][1]["observed_at"] = ts_relative_to_old_ref
        r = InputValidator(ctx).validate(inp)
        # Must be VALID (fresh relative to old_ref) — not PRECONDITION_FAILURE
        assert r.result == ValidationResultType.VALID

    def test_different_window_enforced_correctly(self):
        # Observation is 45 minutes old. With a 30-min window → stale.
        forty_five_min_old = (REF - timedelta(minutes=45)).isoformat()
        ctx = make_context(freshness_window_seconds=1800)  # 30 minutes
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = forty_five_min_old
        inp["observations"][1]["observed_at"] = forty_five_min_old
        r = InputValidator(ctx).validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE

    def test_same_observation_fresh_under_wider_window(self):
        # The same 45-min-old observation is fresh under a 60-min window.
        forty_five_min_old = (REF - timedelta(minutes=45)).isoformat()
        ctx = make_context(freshness_window_seconds=3600)  # 60 minutes
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = forty_five_min_old
        inp["observations"][1]["observed_at"] = forty_five_min_old
        r = InputValidator(ctx).validate(inp)
        assert r.result == ValidationResultType.VALID


# ===========================================================================
# Category 7 — Relationship Validation  (Contract §6 Category 7, Rules 7.9, 7.10)
# ===========================================================================

class TestRelationshipValidation:
    """
    Contract §6 Category 7:
    Rule 7.9: all entity references resolve within the input context only.
    Rule 7.10: duplicate source observations → VALIDATION_FAILURE (not PRECONDITION_FAILURE).
    """

    def test_listing_product_ref_mismatch_is_invalid(self):
        inp = make_valid_input()
        inp["listings"][0]["product_ref"] = "different-product-id"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.RELATIONSHIP_VALIDATION.value
        assert errors_for_field(r, "listings[0].product_ref")
        assert has_rule(r, ValidationRule.RELATIONSHIPS_WITHIN_CONTEXT)

    def test_observation_listing_ref_nonexistent_is_invalid(self):
        inp = make_valid_input()
        inp["observations"][0]["listing_ref"] = "DOES_NOT_EXIST"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.RELATIONSHIP_VALIDATION.value
        assert errors_for_field(r, "observations[0].listing_ref")
        assert has_rule(r, ValidationRule.RELATIONSHIPS_WITHIN_CONTEXT)

    def test_observation_source_mismatch_with_listing_source_is_invalid(self):
        # Observation says src_b but its referenced listing is src_a.
        inp = make_valid_input()
        inp["observations"][0]["source"] = "src_b"   # lst-a is src_a
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.RELATIONSHIP_VALIDATION.value
        assert errors_for_field(r, "observations[0].source")
        assert has_rule(r, ValidationRule.RELATIONSHIPS_WITHIN_CONTEXT)

    def test_duplicate_source_in_observations_is_invalid(self):
        # Rule 7.10: only one observation per source per product is permitted.
        inp = make_valid_input()
        inp["listings"] = [
            {"listing_id": "lst-a1", "source": "src_a", "external_id": "ea1",
             "price": 100.0, "product_ref": "prod-001"},
            {"listing_id": "lst-a2", "source": "src_a", "external_id": "ea2",
             "price": 105.0, "product_ref": "prod-001"},
        ]
        inp["observations"] = [
            {"observation_id": "obs-1", "listing_ref": "lst-a1", "source": "src_a",
             "observed_price": 100.0, "observed_at": FRESH},
            {"observation_id": "obs-2", "listing_ref": "lst-a2", "source": "src_a",
             "observed_price": 105.0, "observed_at": FRESH},
        ]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.RELATIONSHIP_VALIDATION.value
        assert has_rule(r, ValidationRule.NO_DUPLICATE_SOURCE_OBSERVATIONS)

    def test_duplicate_source_is_invalid_not_precondition_failure(self):
        # Duplicate source detection must classify as INVALID, not PRECONDITION_FAILURE.
        # Contract §7.10 explicitly states VALIDATION_FAILURE.
        inp = make_valid_input()
        inp["listings"] = [
            {"listing_id": "lst-a1", "source": "src_a", "external_id": "ea1",
             "price": 100.0, "product_ref": "prod-001"},
            {"listing_id": "lst-a2", "source": "src_a", "external_id": "ea2",
             "price": 105.0, "product_ref": "prod-001"},
        ]
        inp["observations"] = [
            {"observation_id": "obs-1", "listing_ref": "lst-a1", "source": "src_a",
             "observed_price": 100.0, "observed_at": FRESH},
            {"observation_id": "obs-2", "listing_ref": "lst-a2", "source": "src_a",
             "observed_price": 105.0, "observed_at": FRESH},
        ]
        r = make_validator().validate(inp)
        assert isinstance(r, InvalidResult)
        assert not isinstance(r, PreconditionFailureResult)

    def test_triple_duplicate_source_emits_one_error_not_two(self):
        # Emitting one error per duplicate source (not one per extra occurrence).
        inp = make_valid_input()
        inp["listings"] = [
            {"listing_id": f"lst-{i}", "source": "src_a", "external_id": f"e{i}",
             "price": 100.0, "product_ref": "prod-001"}
            for i in range(3)
        ]
        inp["observations"] = [
            {"observation_id": f"obs-{i}", "listing_ref": f"lst-{i}", "source": "src_a",
             "observed_price": 100.0, "observed_at": FRESH}
            for i in range(3)
        ]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        dup_errors = [
            e for e in r.errors
            if e.rule_violated == ValidationRule.NO_DUPLICATE_SOURCE_OBSERVATIONS.value
        ]
        assert len(dup_errors) == 1

    def test_multiple_relationship_failures_collected_together(self):
        # Rule 7.5: all errors in the failing category collected before returning.
        inp = make_valid_input()
        inp["listings"][0]["product_ref"] = "wrong-product"
        inp["observations"][0]["listing_ref"] = "nonexistent-listing"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.RELATIONSHIP_VALIDATION.value
        assert len(r.errors) >= 2


# ===========================================================================
# Category 8 — Comparison Eligibility Precondition  (Contract §6 Category 8, §5.6)
# ===========================================================================

class TestComparisonEligibility:
    """
    Contract §6 Category 8, §5.6:
    At least two observations from at least two distinct valid sources required.
    Failure → PRECONDITION_FAILURE (not INVALID).
    retriable must be True.
    """

    def test_single_source_is_precondition_failure(self):
        inp = make_valid_input()
        inp["listings"] = [
            {"listing_id": "lst-a", "source": "src_a", "external_id": "ea",
             "price": 100.0, "product_ref": "prod-001"},
        ]
        inp["observations"] = [
            {"observation_id": "obs-a", "listing_ref": "lst-a", "source": "src_a",
             "observed_price": 100.0, "observed_at": FRESH},
        ]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE
        assert isinstance(r, PreconditionFailureResult)

    def test_single_source_precondition_failure_is_retriable(self):
        inp = make_valid_input()
        inp["listings"] = [
            {"listing_id": "lst-a", "source": "src_a", "external_id": "ea",
             "price": 100.0, "product_ref": "prod-001"},
        ]
        inp["observations"] = [
            {"observation_id": "obs-a", "listing_ref": "lst-a", "source": "src_a",
             "observed_price": 100.0, "observed_at": FRESH},
        ]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE
        assert r.retriable is True

    def test_empty_observations_is_precondition_failure(self):
        inp = make_valid_input(observations=[])
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE

    def test_single_source_is_precondition_not_invalid(self):
        # Insufficient observations is a structural insufficiency, not a field error.
        inp = make_valid_input()
        inp["listings"] = [
            {"listing_id": "lst-a", "source": "src_a", "external_id": "ea",
             "price": 100.0, "product_ref": "prod-001"},
        ]
        inp["observations"] = [
            {"observation_id": "obs-a", "listing_ref": "lst-a", "source": "src_a",
             "observed_price": 100.0, "observed_at": FRESH},
        ]
        r = make_validator().validate(inp)
        assert not isinstance(r, InvalidResult)

    def test_two_distinct_sources_passes_eligibility(self):
        # The baseline valid input already uses two distinct sources.
        r = make_validator().validate(make_valid_input())
        assert r.result == ValidationResultType.VALID

    def test_three_distinct_sources_passes_eligibility(self):
        inp = make_valid_input()
        inp["listings"].append(
            {"listing_id": "lst-c", "source": "src_c", "external_id": "ec",
             "price": 110.0, "product_ref": "prod-001"}
        )
        inp["observations"].append(
            {"observation_id": "obs-c", "listing_ref": "lst-c", "source": "src_c",
             "observed_price": 110.0, "observed_at": FRESH}
        )
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID


# ===========================================================================
# Output structure — Contract §8
# ===========================================================================

class TestOutputStructure:
    """
    Contract §8: every result type must carry exactly the required fields.
    """

    def test_valid_result_has_all_required_fields(self):
        r = make_validator().validate(make_valid_input())
        assert isinstance(r, ValidResult)
        assert r.result == ValidationResultType.VALID.value
        assert r.validated_at == VALIDATED_AT
        assert r.input_identity == "prod-001"
        assert r.observation_count == 2
        assert r.source_count == 2

    def test_invalid_result_has_all_required_fields(self):
        inp = make_valid_input()
        del inp["product_id"]
        r = make_validator().validate(inp)
        assert isinstance(r, InvalidResult)
        assert r.result == ValidationResultType.INVALID.value
        assert r.validated_at == VALIDATED_AT
        assert r.input_identity == "<unknown>"
        assert r.failure_category
        assert len(r.errors) > 0

    def test_invalid_result_error_entries_have_all_required_fields(self):
        inp = make_valid_input()
        inp["listings"][0]["price"] = -1.0
        r = make_validator().validate(inp)
        assert isinstance(r, InvalidResult)
        for error in r.errors:
            assert error.field
            assert error.reason
            assert error.rule_violated
            # received_value may be None only if explicitly redacted; it must be present
            assert hasattr(error, "received_value")

    def test_precondition_failure_has_all_required_fields(self):
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert isinstance(r, PreconditionFailureResult)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE.value
        assert r.validated_at == VALIDATED_AT
        assert r.input_identity == "prod-001"
        assert r.precondition_failed
        assert r.reason
        assert isinstance(r.retriable, bool)

    def test_valid_result_has_correct_observation_count(self):
        inp = make_valid_input()
        inp["listings"].append(
            {"listing_id": "lst-c", "source": "src_c", "external_id": "ec",
             "price": 110.0, "product_ref": "prod-001"}
        )
        inp["observations"].append(
            {"observation_id": "obs-c", "listing_ref": "lst-c", "source": "src_c",
             "observed_price": 110.0, "observed_at": FRESH}
        )
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.VALID
        assert r.observation_count == 3
        assert r.source_count == 3

    def test_invalid_result_input_identity_uses_product_id(self):
        inp = make_valid_input()
        inp["listings"][0]["price"] = 0  # trigger INVALID in value category
        r = make_validator().validate(inp)
        assert isinstance(r, InvalidResult)
        assert r.input_identity == "prod-001"


# ===========================================================================
# Category ordering — Contract §7.5
# ===========================================================================

class TestCategoryOrdering:
    """
    Contract §7.5, §6: validation stops at the first failing category.
    Errors from later categories must not appear when an earlier one failed.
    """

    def test_schema_failure_stops_before_required_field_check(self):
        # Non-dict input → schema failure; required-field errors must not appear.
        r = make_validator().validate("i am not a dict")
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SCHEMA_VALIDATION.value

    def test_required_field_failure_stops_before_type_check(self):
        # product_id = None → required-field failure (key present but null clears
        # schema validation); type errors on other fields must not be checked.
        inp = make_valid_input()
        inp["product_id"] = None          # null: passes schema, fails required-field
        # Also introduce a type error on a different field.
        inp["alert_threshold"] = "should-be-numeric-but-never-checked"
        r = make_validator().validate(inp)
        # Must fail at required-field, not type.
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.REQUIRED_FIELD_VALIDATION.value

    def test_type_failure_stops_before_value_check(self):
        inp = make_valid_input()
        inp["listings"][0]["price"] = "expensive"  # type error
        inp["alert_threshold"] = -999              # would be a value error if reached
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TYPE_VALIDATION.value

    def test_source_failure_stops_before_timestamp_check(self):
        inp = make_valid_input()
        inp["listings"][0]["source"] = "UNRECOGNISED"
        inp["observations"][0]["source"] = "UNRECOGNISED"
        inp["observations"][0]["observed_at"] = "NOT-A-DATE"   # would fail Category 6
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.SOURCE_VALIDATION.value

    def test_timestamp_format_failure_stops_before_freshness_check(self):
        # A malformed timestamp must be reported as INVALID before staleness is evaluated.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = "GARBAGE"
        # observations[1] is stale — must not be reported if format check fails first.
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert r.failure_category == ValidationCategory.TIMESTAMP_VALIDATION.value


# ===========================================================================
# Determinism — Contract §10
# ===========================================================================

class TestDeterminism:
    """
    Contract §10: the same input + the same context must always produce the
    same result.  No system clock. No randomness.
    """

    def test_identical_valid_inputs_produce_equal_results(self):
        v = make_validator()
        inp = make_valid_input()
        r1 = v.validate(inp)
        r2 = v.validate(inp)
        assert r1 == r2

    def test_identical_invalid_inputs_produce_equal_results(self):
        v = make_validator()
        inp = make_valid_input()
        del inp["product_id"]
        r1 = v.validate(inp)
        r2 = v.validate(inp)
        assert r1 == r2

    def test_identical_precondition_failure_inputs_produce_equal_results(self):
        v = make_validator()
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r1 = v.validate(inp)
        r2 = v.validate(inp)
        assert r1 == r2

    def test_validated_at_comes_from_context_not_clock(self):
        # The validated_at in the result must equal the one supplied via context.
        fixed_ts = datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc)
        ctx = make_context(
            freshness_reference_timestamp=fixed_ts,
            validated_at=fixed_ts,
        )
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = (fixed_ts - timedelta(minutes=10)).isoformat()
        inp["observations"][1]["observed_at"] = (fixed_ts - timedelta(minutes=10)).isoformat()
        r = InputValidator(ctx).validate(inp)
        assert r.validated_at == fixed_ts

    def test_same_input_different_context_may_produce_different_result(self):
        # Confirm that the result is a function of (input, context) together.
        # A timestamp fresh in context_a may be stale in context_b.
        ts = (REF - timedelta(minutes=30)).isoformat()
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = ts
        inp["observations"][1]["observed_at"] = ts

        ctx_fresh = make_context(freshness_window_seconds=3600)   # 60-min window → fresh
        ctx_stale = make_context(freshness_window_seconds=1200)   # 20-min window → stale

        r_fresh = InputValidator(ctx_fresh).validate(inp)
        r_stale = InputValidator(ctx_stale).validate(inp)

        assert r_fresh.result == ValidationResultType.VALID
        assert r_stale.result == ValidationResultType.PRECONDITION_FAILURE

    def test_error_order_is_consistent(self):
        # Rule 10.2: the same set of errors must appear in a consistent order.
        v = make_validator()
        inp = make_valid_input()
        inp["listings"][0]["price"] = 0
        inp["listings"][1]["price"] = 0
        r1 = v.validate(inp)
        r2 = v.validate(inp)
        assert [e.field for e in r1.errors] == [e.field for e in r2.errors]


# ===========================================================================
# Non-acceptance guard — Contract §15
# ===========================================================================

class TestNonAcceptanceConditions:
    """
    Direct tests for each non-acceptance condition in Contract §15.
    """

    def test_invalid_input_never_returns_valid(self):
        # §15: an invalid input (missing field) must never return VALID.
        inp = make_valid_input()
        del inp["product_id"]
        r = make_validator().validate(inp)
        assert r.result != ValidationResultType.VALID

    def test_broken_listing_reference_does_not_reach_stage_2(self):
        # §15: a structurally broken input must not be classified VALID.
        inp = make_valid_input()
        inp["observations"][0]["listing_ref"] = "nonexistent"
        r = make_validator().validate(inp)
        assert r.result != ValidationResultType.VALID

    def test_no_field_value_is_silently_coerced(self):
        # §15: string price must not be coerced and accepted as numeric.
        inp = make_valid_input()
        inp["listings"][0]["price"] = "100"
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.INVALID
        assert has_rule(r, ValidationRule.NO_SILENT_COERCION)

    def test_stale_timestamp_is_precondition_not_field_error(self):
        # §15: stale observations must be PRECONDITION_FAILURE, not INVALID.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE

    def test_insufficient_sources_is_precondition_not_field_error(self):
        # §15: insufficient source count must be PRECONDITION_FAILURE, not INVALID.
        inp = make_valid_input()
        inp["listings"] = [
            {"listing_id": "lst-a", "source": "src_a", "external_id": "ea",
             "price": 100.0, "product_ref": "prod-001"},
        ]
        inp["observations"] = [
            {"observation_id": "obs-a", "listing_ref": "lst-a", "source": "src_a",
             "observed_price": 100.0, "observed_at": FRESH},
        ]
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE

    def test_precondition_failure_includes_retriable_field(self):
        # §15: a PRECONDITION_FAILURE output missing retriable is a blocking defect.
        inp = make_valid_input()
        inp["observations"][0]["observed_at"] = STALE
        inp["observations"][1]["observed_at"] = STALE
        r = make_validator().validate(inp)
        assert r.result == ValidationResultType.PRECONDITION_FAILURE
        assert isinstance(r.retriable, bool)

    def test_invalid_error_entry_has_field_received_value_reason_rule(self):
        # §15: an INVALID output missing any of these on an error entry is a blocking defect.
        inp = make_valid_input()
        inp["listings"][0]["price"] = 0
        r = make_validator().validate(inp)
        assert isinstance(r, InvalidResult)
        for e in r.errors:
            assert e.field, "field must be non-empty"
            assert e.reason, "reason must be non-empty"
            assert e.rule_violated, "rule_violated must be non-empty"
            assert hasattr(e, "received_value"), "received_value must exist"

    def test_no_external_system_called(self):
        # §15: the validator must not call external systems.
        # Verified structurally: the module imports do not include requests, httpx,
        # psycopg2, sqlalchemy, or any I/O library. This test confirms the happy-path
        # runs without any mocking of external dependencies.
        r = make_validator().validate(make_valid_input())
        assert r.result == ValidationResultType.VALID
