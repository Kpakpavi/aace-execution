-- Webhook delivery audit + dedup table.
--
-- Created on Day 4. The in-memory dedup store ships first; the
-- Postgres-backed store added on Day 5 uses this table. Safe to apply
-- multiple times.
--
-- Lookup pattern: "has this opportunity_id been sent successfully in
-- the last N hours?"  ->  ORDER BY sent_at DESC LIMIT 1.

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id               BIGSERIAL    PRIMARY KEY,
    opportunity_id   VARCHAR(255) NOT NULL,
    status           VARCHAR(32)  NOT NULL,   -- delivered | failed | deduped
    attempts         INTEGER      NOT NULL,
    last_status_code INTEGER,
    last_error       TEXT,
    sent_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_opp_id_sent_at
    ON webhook_deliveries (opportunity_id, sent_at DESC);
