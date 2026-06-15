-- Operator watchlist: keywords the operator is actively hunting.
-- When a new cross-source opportunity's product_key contains an entry
-- here (case-insensitive substring), the dashboard surfaces it in a
-- dedicated panel and (future) alert thresholds can be relaxed for it.
-- Safe to apply multiple times.

CREATE TABLE IF NOT EXISTS watchlist_entries (
    id              BIGSERIAL    PRIMARY KEY,
    keyword         TEXT         NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    active          BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Case-insensitive uniqueness — "Apple Watch" and "apple watch" are
-- the same entry from the operator's perspective.
CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_keyword_lower
    ON watchlist_entries (LOWER(keyword));

-- The matcher always filters on active=TRUE, so a partial index keeps
-- the scan tight even when the operator has accumulated dozens of
-- soft-disabled keywords over time.
CREATE INDEX IF NOT EXISTS idx_watchlist_active
    ON watchlist_entries (active) WHERE active = TRUE;
