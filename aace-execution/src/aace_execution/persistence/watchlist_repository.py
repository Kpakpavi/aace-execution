"""Persistence layer for the operator watchlist.

A *watchlist entry* is a keyword the operator is hunting for. When the
worker detects a cross-source opportunity whose ``product_key``
contains the keyword (case-insensitive substring), the dashboard
surfaces it in a dedicated "Watchlist Matches" panel.

This module owns the CRUD surface for the ``watchlist_entries`` table
plus a small matching helper used at API read time. Keeping the match
logic next to the storage layer means tests don't need to coordinate
across modules.

DB connection is injected at construction (same pattern as
``WorkerOpportunityWriter``) so the repository is unit-testable
against a MagicMock cursor — no live Postgres required for the
non-integration suite.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WatchlistEntry:
    """One row from ``watchlist_entries``."""

    id: int
    keyword: str
    description: str
    active: bool
    created_at: datetime | None
    updated_at: datetime | None


class WatchlistError(Exception):
    """Raised for caller-induced repository errors (bad input, conflict).

    DB transport errors propagate as their underlying exception types
    so the API layer can map them to 5xx without ambiguity.
    """


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Trim, collapse internal whitespace, lowercase for the uniqueness check.
_WHITESPACE_RE = re.compile(r"\s+")

MIN_KEYWORD_LENGTH = 2
MAX_KEYWORD_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 500


def normalize_keyword(raw: str) -> str:
    """Trim + collapse whitespace. Used for both storage and matching.

    NOTE: storage preserves the operator's casing for display ("Apple
    Watch"), but uniqueness is enforced on ``LOWER(keyword)`` by the
    SQL index so "APPLE WATCH" doesn't accidentally duplicate.
    """
    if not isinstance(raw, str):
        raise WatchlistError("keyword must be a string")
    cleaned = _WHITESPACE_RE.sub(" ", raw.strip())
    if len(cleaned) < MIN_KEYWORD_LENGTH:
        raise WatchlistError(
            f"keyword must be at least {MIN_KEYWORD_LENGTH} characters"
        )
    if len(cleaned) > MAX_KEYWORD_LENGTH:
        raise WatchlistError(
            f"keyword must be at most {MAX_KEYWORD_LENGTH} characters"
        )
    return cleaned


def normalize_description(raw: str | None) -> str:
    """Empty string is the canonical "no description" value."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise WatchlistError("description must be a string")
    cleaned = raw.strip()
    if len(cleaned) > MAX_DESCRIPTION_LENGTH:
        raise WatchlistError(
            f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
        )
    return cleaned


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


_SELECT_COLUMNS = (
    "id, keyword, description, active, created_at, updated_at"
)


class WatchlistRepository:
    """CRUD over ``watchlist_entries``."""

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_entries(self, *, active_only: bool = False) -> list[WatchlistEntry]:
        """Return every entry, newest first. Soft-deleted entries
        included unless ``active_only=True``."""
        sql = f"SELECT {_SELECT_COLUMNS} FROM watchlist_entries"
        params: list[Any] = []
        if active_only:
            sql += " WHERE active = TRUE"
        sql += " ORDER BY created_at DESC, id DESC"
        with self._conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return [_row_to_entry(row) for row in cursor.fetchall()]

    def get_entry(self, entry_id: int) -> WatchlistEntry | None:
        """Look up one entry by primary key, or ``None`` if missing."""
        sql = f"SELECT {_SELECT_COLUMNS} FROM watchlist_entries WHERE id = %s"
        with self._conn.cursor() as cursor:
            cursor.execute(sql, (int(entry_id),))
            row = cursor.fetchone()
            return _row_to_entry(row) if row is not None else None

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add_entry(
        self,
        *,
        keyword: str,
        description: str = "",
    ) -> WatchlistEntry:
        """Insert a new entry. Raises ``WatchlistError`` on duplicate
        keyword (case-insensitive)."""
        kw = normalize_keyword(keyword)
        desc = normalize_description(description)
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO watchlist_entries (keyword, description) "
                    "VALUES (%s, %s) "
                    f"RETURNING {_SELECT_COLUMNS}",
                    (kw, desc),
                )
                row = cursor.fetchone()
            self._conn.commit()
            return _row_to_entry(row)
        except Exception as exc:  # noqa: BLE001
            # Best-effort rollback so the transaction doesn't poison
            # the next call on the shared connection.
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            # psycopg surfaces unique-violation as IntegrityError; we
            # don't import it directly to keep this module loadable in
            # contexts where psycopg isn't installed.
            err_name = type(exc).__name__
            if "Integrity" in err_name or "Unique" in err_name:
                raise WatchlistError(
                    f"keyword {kw!r} is already in the watchlist"
                ) from exc
            raise

    def update_entry(
        self,
        entry_id: int,
        *,
        keyword: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> WatchlistEntry | None:
        """Partial update. Returns ``None`` if no such id.

        Any field passed as ``None`` is left untouched. ``updated_at``
        is bumped automatically.
        """
        sets: list[str] = []
        params: list[Any] = []
        if keyword is not None:
            sets.append("keyword = %s")
            params.append(normalize_keyword(keyword))
        if description is not None:
            sets.append("description = %s")
            params.append(normalize_description(description))
        if active is not None:
            if not isinstance(active, bool):
                raise WatchlistError("active must be a boolean")
            sets.append("active = %s")
            params.append(active)
        if not sets:
            # Nothing to update — return current state.
            return self.get_entry(entry_id)
        sets.append("updated_at = NOW()")
        params.append(int(entry_id))
        sql = (
            "UPDATE watchlist_entries SET "
            + ", ".join(sets)
            + f" WHERE id = %s RETURNING {_SELECT_COLUMNS}"
        )
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                row = cursor.fetchone()
            self._conn.commit()
            return _row_to_entry(row) if row is not None else None
        except Exception as exc:  # noqa: BLE001
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            err_name = type(exc).__name__
            if "Integrity" in err_name or "Unique" in err_name:
                raise WatchlistError(
                    f"keyword {keyword!r} conflicts with an existing entry"
                ) from exc
            raise

    def delete_entry(self, entry_id: int) -> bool:
        """Hard-delete an entry. Returns ``True`` if a row was removed.

        Most operator-side flows should prefer ``update_entry(active=False)``
        (soft delete) so we keep audit history; hard delete is offered
        for keyword typos and the like.
        """
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM watchlist_entries WHERE id = %s",
                    (int(entry_id),),
                )
                deleted = cursor.rowcount
            self._conn.commit()
            return deleted > 0
        except Exception:
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise


# ---------------------------------------------------------------------------
# Match helper (used by the API enrichment path)
# ---------------------------------------------------------------------------


def match_keywords(
    product_key: str,
    keywords: Iterable[str],
) -> list[str]:
    """Return the subset of ``keywords`` whose lowercase form appears
    as a substring of ``product_key``'s lowercase form.

    Case-insensitive; whitespace within a keyword is significant
    ("apple watch" matches "11 apple watch series" but "applewatch"
    does not). Returns the matching keywords in their original casing
    so the dashboard can display them as the operator typed them.
    """
    if not product_key or not isinstance(product_key, str):
        return []
    haystack = product_key.lower()
    matches: list[str] = []
    for raw in keywords:
        if not isinstance(raw, str) or not raw.strip():
            continue
        needle = raw.lower().strip()
        if not needle:
            continue
        if needle in haystack:
            matches.append(raw)
    return matches


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _row_to_entry(row: Any) -> WatchlistEntry:
    """Turn a DB row tuple into a typed :class:`WatchlistEntry`."""
    return WatchlistEntry(
        id=int(row[0]),
        keyword=str(row[1]),
        description=str(row[2] or ""),
        active=bool(row[3]),
        created_at=row[4],
        updated_at=row[5],
    )
