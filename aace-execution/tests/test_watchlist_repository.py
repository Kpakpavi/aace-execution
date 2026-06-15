"""Unit tests for the watchlist persistence layer.

DB connection is fully mocked — these run offline. Integration tests
that exercise the real Postgres table live in (skipped-by-default)
test_api_watchlist.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from aace_execution.persistence.watchlist_repository import (
    WatchlistEntry,
    WatchlistError,
    WatchlistRepository,
    match_keywords,
    normalize_description,
    normalize_keyword,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)


def _row(
    *,
    id: int = 1,
    keyword: str = "apple watch",
    description: str = "",
    active: bool = True,
    created_at: datetime | None = _NOW,
    updated_at: datetime | None = _NOW,
) -> tuple:
    return (id, keyword, description, active, created_at, updated_at)


def _mk_connection(*, fetchone=None, fetchall=None, rowcount=1, raises=None):
    """Return a stand-in connection object.

    The cursor returned by ``connection.cursor()`` is itself a
    context-manager (the production code uses ``with self._conn.cursor()``).
    """
    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=fetchone)
    cursor.fetchall = MagicMock(return_value=fetchall or [])
    cursor.rowcount = rowcount
    if raises is not None:
        cursor.execute = MagicMock(side_effect=raises)

    # Context-manager wiring — cursor.__enter__ returns the cursor itself.
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    # Expose the cursor for assertions
    conn._cursor = cursor
    return conn


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestNormalizeKeyword:
    def test_strips_whitespace(self):
        assert normalize_keyword("  apple watch  ") == "apple watch"

    def test_collapses_internal_whitespace(self):
        assert normalize_keyword("apple   watch\tseries") == "apple watch series"

    def test_too_short_rejected(self):
        with pytest.raises(WatchlistError):
            normalize_keyword("a")

    def test_too_long_rejected(self):
        with pytest.raises(WatchlistError):
            normalize_keyword("x" * 101)

    def test_non_string_rejected(self):
        with pytest.raises(WatchlistError):
            normalize_keyword(123)  # type: ignore[arg-type]

    def test_preserves_casing(self):
        assert normalize_keyword("Apple Watch") == "Apple Watch"


class TestNormalizeDescription:
    def test_none_becomes_empty(self):
        assert normalize_description(None) == ""

    def test_strips_whitespace(self):
        assert normalize_description("  notes  ") == "notes"

    def test_too_long_rejected(self):
        with pytest.raises(WatchlistError):
            normalize_description("x" * 501)


# ---------------------------------------------------------------------------
# match_keywords
# ---------------------------------------------------------------------------


class TestMatchKeywords:
    def test_substring_match_case_insensitive(self):
        matches = match_keywords(
            "11 apple watch series gps smartwatch",
            ["Apple Watch", "PS5", "macbook"],
        )
        assert matches == ["Apple Watch"]

    def test_multiple_matches(self):
        matches = match_keywords(
            "apple watch macbook bundle",
            ["apple watch", "macbook"],
        )
        assert set(matches) == {"apple watch", "macbook"}

    def test_no_match_returns_empty(self):
        assert match_keywords("apple watch", ["nintendo switch"]) == []

    def test_empty_product_key_returns_empty(self):
        assert match_keywords("", ["apple watch"]) == []

    def test_skips_blank_keywords(self):
        # Blank/whitespace keywords from the DB should be silently skipped
        # rather than matching everything via the empty substring.
        matches = match_keywords("apple watch", ["", "   ", "apple"])
        assert matches == ["apple"]

    def test_preserves_original_keyword_casing(self):
        # Operator typed "Apple Watch" — the match list returns the same
        # casing for display, not the lowercased haystack version.
        matches = match_keywords(
            "11 apple watch series",
            ["Apple Watch"],
        )
        assert matches == ["Apple Watch"]

    def test_word_boundary_not_required(self):
        # "macbook" should match "macbookair" — this is a substring
        # match, not a word match. Operators sometimes type partial
        # tokens.
        assert match_keywords("macbookair m3", ["macbook"]) == ["macbook"]


# ---------------------------------------------------------------------------
# Repository: list + get
# ---------------------------------------------------------------------------


class TestListEntries:
    def test_list_all_returns_typed_entries(self):
        conn = _mk_connection(fetchall=[
            _row(id=1, keyword="apple watch", active=True),
            _row(id=2, keyword="ps5", active=False),
        ])
        repo = WatchlistRepository(conn)
        entries = repo.list_entries()
        assert len(entries) == 2
        assert all(isinstance(e, WatchlistEntry) for e in entries)
        assert entries[0].keyword == "apple watch"
        assert entries[1].active is False

    def test_list_active_only_filters_in_sql(self):
        conn = _mk_connection(fetchall=[
            _row(id=1, keyword="apple watch", active=True),
        ])
        repo = WatchlistRepository(conn)
        repo.list_entries(active_only=True)
        executed_sql = conn._cursor.execute.call_args[0][0]
        assert "WHERE active = TRUE" in executed_sql

    def test_default_ordering_newest_first(self):
        conn = _mk_connection(fetchall=[])
        repo = WatchlistRepository(conn)
        repo.list_entries()
        executed_sql = conn._cursor.execute.call_args[0][0]
        assert "ORDER BY created_at DESC" in executed_sql


class TestGetEntry:
    def test_returns_entry_when_found(self):
        conn = _mk_connection(fetchone=_row(id=42, keyword="ps5"))
        repo = WatchlistRepository(conn)
        entry = repo.get_entry(42)
        assert entry is not None
        assert entry.id == 42
        assert entry.keyword == "ps5"

    def test_returns_none_when_missing(self):
        conn = _mk_connection(fetchone=None)
        repo = WatchlistRepository(conn)
        assert repo.get_entry(999) is None


# ---------------------------------------------------------------------------
# Repository: add
# ---------------------------------------------------------------------------


class TestAddEntry:
    def test_inserts_and_returns_typed_entry(self):
        conn = _mk_connection(fetchone=_row(id=7, keyword="apple watch"))
        repo = WatchlistRepository(conn)
        entry = repo.add_entry(keyword="apple watch", description="refurbs")
        assert entry.id == 7
        assert entry.keyword == "apple watch"
        conn.commit.assert_called_once()

    def test_normalizes_keyword_before_insert(self):
        conn = _mk_connection(fetchone=_row())
        repo = WatchlistRepository(conn)
        repo.add_entry(keyword="  apple   watch  ")
        params = conn._cursor.execute.call_args[0][1]
        assert params[0] == "apple watch"

    def test_unique_violation_maps_to_watchlist_error(self):
        # psycopg surfaces this as ``IntegrityError`` whose class name
        # contains "Integrity" — we match on substring so the code
        # works whether or not psycopg is importable here.
        class _FakeIntegrityError(Exception):
            pass
        _FakeIntegrityError.__name__ = "IntegrityError"
        conn = _mk_connection(raises=_FakeIntegrityError("duplicate"))
        repo = WatchlistRepository(conn)
        with pytest.raises(WatchlistError) as excinfo:
            repo.add_entry(keyword="apple watch")
        assert "already" in str(excinfo.value).lower()
        conn.rollback.assert_called()

    def test_invalid_keyword_rejected_before_db(self):
        conn = _mk_connection()
        repo = WatchlistRepository(conn)
        with pytest.raises(WatchlistError):
            repo.add_entry(keyword="x")  # too short
        conn._cursor.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Repository: update
# ---------------------------------------------------------------------------


class TestUpdateEntry:
    def test_partial_update_only_changes_provided_fields(self):
        conn = _mk_connection(
            fetchone=_row(id=1, keyword="apple watch", active=False),
        )
        repo = WatchlistRepository(conn)
        entry = repo.update_entry(1, active=False)
        assert entry is not None
        assert entry.active is False
        sql = conn._cursor.execute.call_args[0][0]
        assert "active = %s" in sql
        assert "keyword = %s" not in sql
        assert "description = %s" not in sql

    def test_update_returns_none_when_id_missing(self):
        conn = _mk_connection(fetchone=None)
        repo = WatchlistRepository(conn)
        assert repo.update_entry(999, active=False) is None

    def test_update_bumps_updated_at(self):
        conn = _mk_connection(fetchone=_row())
        repo = WatchlistRepository(conn)
        repo.update_entry(1, active=False)
        sql = conn._cursor.execute.call_args[0][0]
        assert "updated_at = NOW()" in sql

    def test_update_with_no_fields_returns_current_state(self):
        # When the caller passes nothing, fall back to a get() so the
        # API can still return the row without doing a no-op UPDATE.
        conn = _mk_connection(fetchone=_row(id=5))
        repo = WatchlistRepository(conn)
        entry = repo.update_entry(5)
        assert entry is not None
        assert entry.id == 5

    def test_invalid_active_rejected(self):
        conn = _mk_connection()
        repo = WatchlistRepository(conn)
        with pytest.raises(WatchlistError):
            repo.update_entry(1, active="yes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Repository: delete
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    def test_returns_true_when_row_deleted(self):
        conn = _mk_connection(rowcount=1)
        repo = WatchlistRepository(conn)
        assert repo.delete_entry(1) is True
        conn.commit.assert_called_once()

    def test_returns_false_when_no_row(self):
        conn = _mk_connection(rowcount=0)
        repo = WatchlistRepository(conn)
        assert repo.delete_entry(999) is False

    def test_propagates_db_errors(self):
        conn = _mk_connection(raises=RuntimeError("connection lost"))
        repo = WatchlistRepository(conn)
        with pytest.raises(RuntimeError):
            repo.delete_entry(1)
        conn.rollback.assert_called()
