"""
Named SQL constants for the AACE execution persistence layer.

All SQL statements targeting the PostgreSQL schema defined in
POSTGRES_PERSISTENCE_SCHEMA.md. Each constant is a static string with
psycopg-compatible %(name)s parameter placeholders. No SQL is constructed
dynamically. No string concatenation or interpolation.
"""

# ---------------------------------------------------------------------------
# pipeline_results
# ---------------------------------------------------------------------------

SELECT_EXISTING_PIPELINE_RESULT: str = """
    SELECT result_classification
    FROM pipeline_results
    WHERE pipeline_execution_id = %(pipeline_execution_id)s
"""

INSERT_PIPELINE_RESULT: str = """
    INSERT INTO pipeline_results (
        pipeline_execution_id,
        product_id,
        result_classification,
        stage_reached,
        result_timestamp,
        stage_outcome_summary,
        retry_eligible,
        failure_stage,
        failure_reason
    ) VALUES (
        %(pipeline_execution_id)s,
        %(product_id)s,
        %(result_classification)s,
        %(stage_reached)s,
        %(result_timestamp)s,
        %(stage_outcome_summary)s,
        %(retry_eligible)s,
        %(failure_stage)s,
        %(failure_reason)s
    )
"""

UPDATE_PIPELINE_RESULT_FROM_FAILURE: str = """
    UPDATE pipeline_results
    SET
        product_id = %(product_id)s,
        result_classification = %(result_classification)s,
        stage_reached = %(stage_reached)s,
        result_timestamp = %(result_timestamp)s,
        stage_outcome_summary = %(stage_outcome_summary)s,
        retry_eligible = %(retry_eligible)s,
        failure_stage = %(failure_stage)s,
        failure_reason = %(failure_reason)s
    WHERE
        pipeline_execution_id = %(pipeline_execution_id)s
        AND result_classification = 'PROCESSING_FAILURE'
"""

# ---------------------------------------------------------------------------
# opportunities
# ---------------------------------------------------------------------------

INSERT_OPPORTUNITY: str = """
    INSERT INTO opportunities (
        pipeline_execution_id,
        product_id,
        pair_id,
        result_classification,
        discrepancy_rule_id,
        discrepancy_source_a,
        discrepancy_source_b,
        price_a,
        price_b,
        absolute_difference,
        percentage_difference,
        score,
        score_result_id,
        scoring_factors_applied,
        score_range,
        alert_decision,
        alert_decision_id,
        suppression_reason,
        opportunity_timestamp
    ) VALUES (
        %(pipeline_execution_id)s,
        %(product_id)s,
        %(pair_id)s,
        %(result_classification)s,
        %(discrepancy_rule_id)s,
        %(discrepancy_source_a)s,
        %(discrepancy_source_b)s,
        %(price_a)s,
        %(price_b)s,
        %(absolute_difference)s,
        %(percentage_difference)s,
        %(score)s,
        %(score_result_id)s,
        %(scoring_factors_applied)s,
        %(score_range)s,
        %(alert_decision)s,
        %(alert_decision_id)s,
        %(suppression_reason)s,
        %(opportunity_timestamp)s
    )
    ON CONFLICT (pipeline_execution_id) DO NOTHING
"""

# ---------------------------------------------------------------------------
# alert_decisions
# ---------------------------------------------------------------------------

INSERT_ALERT_DECISION: str = """
    INSERT INTO alert_decisions (
        pipeline_execution_id,
        notification_type,
        alert_decision_id,
        product_id,
        pair_id,
        score,
        alert_threshold,
        threshold_met,
        decision_result,
        suppression_reason,
        decision_basis,
        duplicate_check_result,
        decision_reference_timestamp
    ) VALUES (
        %(pipeline_execution_id)s,
        %(notification_type)s,
        %(alert_decision_id)s,
        %(product_id)s,
        %(pair_id)s,
        %(score)s,
        %(alert_threshold)s,
        %(threshold_met)s,
        %(decision_result)s,
        %(suppression_reason)s,
        %(decision_basis)s,
        %(duplicate_check_result)s,
        %(decision_reference_timestamp)s
    )
    ON CONFLICT (pipeline_execution_id, notification_type) DO NOTHING
"""

# ---------------------------------------------------------------------------
# audit_records
# ---------------------------------------------------------------------------

INSERT_AUDIT_RECORD: str = """
    INSERT INTO audit_records (
        pipeline_execution_id,
        product_id,
        result_classification,
        result_timestamp,
        stage_outcome_summary,
        discrepancy_rule_applied,
        score,
        scoring_factor_summary,
        alert_decision,
        failure_stage,
        failure_reason,
        early_exit_stage,
        early_exit_reason,
        persistence_outcome,
        persistence_failure_detail,
        audit_written_at
    ) VALUES (
        %(pipeline_execution_id)s,
        %(product_id)s,
        %(result_classification)s,
        %(result_timestamp)s,
        %(stage_outcome_summary)s,
        %(discrepancy_rule_applied)s,
        %(score)s,
        %(scoring_factor_summary)s,
        %(alert_decision)s,
        %(failure_stage)s,
        %(failure_reason)s,
        %(early_exit_stage)s,
        %(early_exit_reason)s,
        %(persistence_outcome)s,
        %(persistence_failure_detail)s,
        now()
    )
"""
