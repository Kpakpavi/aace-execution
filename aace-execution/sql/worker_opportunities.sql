-- Worker opportunity log — what the v0.1.0 scheduled worker actually
-- found and shipped to the AI agent. Read by the Streamlit dashboard's
-- "Live worker output" panel. Safe to apply multiple times.

CREATE TABLE IF NOT EXISTS worker_opportunities (
    id                BIGSERIAL    PRIMARY KEY,
    opportunity_id    VARCHAR(255) NOT NULL,
    product_key       TEXT         NOT NULL,
    sources           TEXT         NOT NULL,   -- comma-separated
    source_count      INTEGER      NOT NULL,
    min_price         NUMERIC(14, 2) NOT NULL,
    max_price         NUMERIC(14, 2) NOT NULL,
    absolute_spread   NUMERIC(14, 2) NOT NULL,
    percent_spread    NUMERIC(8, 5)  NOT NULL,
    score             NUMERIC(6, 4)  NOT NULL,
    listings_json     JSONB         NOT NULL,
    delivery_status   VARCHAR(32)   NOT NULL,  -- delivered | deduped | failed
    detected_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_worker_opp_detected_at
    ON worker_opportunities (detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_worker_opp_score
    ON worker_opportunities (score DESC);

CREATE INDEX IF NOT EXISTS idx_worker_opp_id
    ON worker_opportunities (opportunity_id);
