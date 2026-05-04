-- AACE execution persistence schema.
-- Implements Contracts/persistence/POSTGRES_PERSISTENCE_SCHEMA.md.

CREATE TABLE pipeline_results (
    pipeline_execution_id   TEXT        NOT NULL,
    product_id              TEXT        NOT NULL,
    result_classification   TEXT        NOT NULL,
    stage_reached           TEXT        NOT NULL,
    result_timestamp        TIMESTAMPTZ NOT NULL,
    stage_outcome_summary   JSONB       NOT NULL,
    retry_eligible          BOOLEAN,
    failure_stage           TEXT,
    failure_reason          TEXT,
    CONSTRAINT pipeline_results_pkey
        PRIMARY KEY (pipeline_execution_id),
    CONSTRAINT pipeline_results_result_classification_check
        CHECK (result_classification IN (
            'OPPORTUNITY_DETECTED',
            'OPPORTUNITY_SCORED_NO_ALERT',
            'NO_OPPORTUNITY',
            'NO_OP',
            'VALIDATION_FAILURE',
            'PRECONDITION_FAILURE',
            'PROCESSING_FAILURE'
        ))
);

CREATE TABLE opportunities (
    pipeline_execution_id    TEXT        NOT NULL,
    product_id               TEXT        NOT NULL,
    pair_id                  TEXT        NOT NULL,
    result_classification    TEXT        NOT NULL,
    discrepancy_rule_id      TEXT        NOT NULL,
    discrepancy_source_a     TEXT        NOT NULL,
    discrepancy_source_b     TEXT        NOT NULL,
    price_a                  NUMERIC     NOT NULL,
    price_b                  NUMERIC     NOT NULL,
    absolute_difference      NUMERIC     NOT NULL,
    percentage_difference    NUMERIC     NOT NULL,
    score                    NUMERIC     NOT NULL,
    score_result_id          TEXT        NOT NULL,
    scoring_factors_applied  JSONB       NOT NULL,
    score_range              JSONB       NOT NULL,
    alert_decision           TEXT        NOT NULL,
    alert_decision_id        TEXT        NOT NULL,
    suppression_reason       TEXT,
    opportunity_timestamp    TIMESTAMPTZ NOT NULL,
    CONSTRAINT opportunities_pkey
        PRIMARY KEY (pipeline_execution_id),
    CONSTRAINT opportunities_pipeline_execution_id_fkey
        FOREIGN KEY (pipeline_execution_id)
        REFERENCES pipeline_results (pipeline_execution_id),
    CONSTRAINT opportunities_result_classification_check
        CHECK (result_classification IN (
            'OPPORTUNITY_DETECTED',
            'OPPORTUNITY_SCORED_NO_ALERT'
        )),
    CONSTRAINT opportunities_alert_decision_check
        CHECK (alert_decision IN ('ALERT_ELIGIBLE', 'NO_ALERT'))
);

CREATE TABLE alert_decisions (
    pipeline_execution_id         TEXT        NOT NULL,
    notification_type             TEXT        NOT NULL,
    alert_decision_id             TEXT        NOT NULL,
    product_id                    TEXT        NOT NULL,
    pair_id                       TEXT        NOT NULL,
    score                         NUMERIC     NOT NULL,
    alert_threshold               NUMERIC     NOT NULL,
    threshold_met                 BOOLEAN     NOT NULL,
    decision_result               TEXT        NOT NULL,
    suppression_reason            TEXT,
    decision_basis                JSONB       NOT NULL,
    duplicate_check_result        TEXT        NOT NULL,
    decision_reference_timestamp  TIMESTAMPTZ NOT NULL,
    CONSTRAINT alert_decisions_pkey
        PRIMARY KEY (pipeline_execution_id, notification_type),
    CONSTRAINT alert_decisions_pipeline_execution_id_fkey
        FOREIGN KEY (pipeline_execution_id)
        REFERENCES pipeline_results (pipeline_execution_id),
    CONSTRAINT alert_decisions_alert_decision_id_key
        UNIQUE (alert_decision_id),
    CONSTRAINT alert_decisions_decision_result_check
        CHECK (decision_result IN ('ALERT_ELIGIBLE', 'NO_ALERT')),
    CONSTRAINT alert_decisions_duplicate_check_result_check
        CHECK (duplicate_check_result IN (
            'NO_PRIOR_ALERT',
            'PRIOR_ALERT_EXISTS'
        ))
);

CREATE TABLE audit_records (
    id                           BIGSERIAL,
    pipeline_execution_id        TEXT        NOT NULL,
    product_id                   TEXT        NOT NULL,
    result_classification        TEXT        NOT NULL,
    result_timestamp             TIMESTAMPTZ NOT NULL,
    stage_outcome_summary        JSONB       NOT NULL,
    discrepancy_rule_applied     TEXT,
    score                        NUMERIC,
    scoring_factor_summary       JSONB,
    alert_decision               TEXT,
    failure_stage                TEXT,
    failure_reason               TEXT,
    early_exit_stage             TEXT,
    early_exit_reason            TEXT,
    persistence_outcome          TEXT        NOT NULL,
    persistence_failure_detail   TEXT,
    audit_written_at             TIMESTAMPTZ NOT NULL,
    CONSTRAINT audit_records_pkey
        PRIMARY KEY (id),
    CONSTRAINT audit_records_result_classification_check
        CHECK (result_classification IN (
            'OPPORTUNITY_DETECTED',
            'OPPORTUNITY_SCORED_NO_ALERT',
            'NO_OPPORTUNITY',
            'NO_OP',
            'VALIDATION_FAILURE',
            'PRECONDITION_FAILURE',
            'PROCESSING_FAILURE'
        )),
    CONSTRAINT audit_records_persistence_outcome_check
        CHECK (persistence_outcome IN (
            'ALL_WRITES_SUCCEEDED',
            'PARTIAL_WRITE_FAILURE',
            'RESULT_WRITE_FAILED'
        ))
);

CREATE INDEX audit_records_pipeline_execution_id_idx
    ON audit_records (pipeline_execution_id);
