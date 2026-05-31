"""Local demo: runs one full Worker tick and prints what happened.

This is the "does it actually work end-to-end" walkthrough — fetch
real listings from Slickdeals + DealNews, match across sources, score,
and POST the survivors to whichever webhook URL you set.

Usage (one-shot, from aace-execution/):

    AGENT_WEBHOOK_URL="https://webhook.site/<your-id>" \\
    AGENT_WEBHOOK_SECRET="demo-secret" \\
    SCORER_MIN_ABS_SPREAD=0.50 \\
    SCORER_MIN_PCT_SPREAD=0.005 \\
    uv run python scripts/local_demo.py

The two SCORER_* env vars are intentionally lowered for the demo so
you actually see matches with current real-world data. Production
defaults are 5% / $5 minimum spread.

Set AGENT_WEBHOOK_URL to a free disposable URL from
https://webhook.site so you can watch the signed POSTs arrive in
your browser tab while the demo runs.
"""

from __future__ import annotations

import os
import sys


def _ensure_ssl_certs() -> None:
    """macOS python.org Python ships without CA roots — patch with certifi."""
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass


def main() -> None:
    _ensure_ssl_certs()

    if not os.environ.get("AGENT_WEBHOOK_URL"):
        print(
            "ERROR: set AGENT_WEBHOOK_URL\n"
            "  Grab a free disposable URL from https://webhook.site",
            file=sys.stderr,
        )
        sys.exit(1)
    os.environ.setdefault("AGENT_WEBHOOK_SECRET", "demo-secret")

    # Import after env is set so the worker reads the right values.
    from aace_execution.worker import _build_default_worker

    bar = "=" * 64
    print()
    print(bar)
    print("AACE local demo  -  one full worker tick")
    print(bar)
    print()

    worker = _build_default_worker()
    result = worker.run_once()

    print(f"Fetched {result.listings_fetched} priced listings:")
    for src, count in result.per_source_counts.items():
        print(f"  - {src}: {count}")
    for src, err in result.per_source_errors.items():
        print(f"  - {src}: ERROR  {err}")
    if not result.per_source_counts and not result.per_source_errors:
        print("  (no connectors registered)")
    print()

    print(f"Cross-source match groups : {result.match_groups}")
    print(f"Above-threshold scored    : {result.scored_opportunities}")
    print()

    if result.delivery_results:
        print("Webhook deliveries:")
        for delivery in result.delivery_results:
            opp_label = delivery.opportunity_id
            if len(opp_label) > 56:
                opp_label = opp_label[:53] + "..."
            attempts = (
                f"{delivery.attempts} attempt(s)"
                if delivery.attempts
                else "0 attempts (dedup)"
            )
            code = (
                f"  status={delivery.last_status_code}"
                if delivery.last_status_code is not None
                else ""
            )
            print(f"  [{delivery.status:>9}]  {opp_label:<58}  ({attempts}){code}")
            if delivery.last_error:
                print(f"             error: {delivery.last_error}")
    else:
        print("No opportunities crossed the score threshold this tick.")
        print("Tip: lower SCORER_MIN_ABS_SPREAD / SCORER_MIN_PCT_SPREAD.")
    print()

    # ------------------------------------------------------------------
    # Diagnostic: top near-miss cross-source pairs.
    # This proves the matcher is doing real work even when no pair
    # crosses the production similarity threshold — useful for tuning
    # and for visibility while v0.1.0 only has two sources.
    # ------------------------------------------------------------------
    _print_near_miss_report(top_n=5)

    print(bar)
    print(
        "Refresh your webhook.site tab to see any signed POSTs the\n"
        "AI agent would have received this tick."
    )
    print(bar)
    print()


def _print_near_miss_report(*, top_n: int = 5) -> None:
    """Re-fetch sources and print the top cross-source similarity pairs.

    Costs one extra fetch per source (the worker already fetched once
    above), but it's a demo — the visibility is worth it.
    """
    from aace_execution.connectors._helpers import (
        _jaccard_similarity,
        _tokenize_title,
    )
    from aace_execution.connectors.bensbargains import BensBargainsConnector
    from aace_execution.connectors.dealnews import DealNewsConnector
    from aace_execution.connectors.slickdeals import SlickdealsConnector

    print("Diagnostic: top cross-source title similarities")
    print("(matcher works on real data even when no pair crosses threshold)")
    print()

    listings = []
    for connector in (
        SlickdealsConnector(),
        DealNewsConnector(),
        BensBargainsConnector(),
    ):
        try:
            listings.extend(connector.run())
        except Exception as exc:
            print(f"  (could not refetch {connector.name}: {exc})")

    # Pre-tokenize once per listing.
    tokenized = [(listing, _tokenize_title(listing.title)) for listing in listings]
    tokenized = [(listing, tokens) for (listing, tokens) in tokenized if tokens]

    # Compute every cross-source pair similarity.
    pairs: list[tuple[float, object, object]] = []
    for i in range(len(tokenized)):
        li, ti = tokenized[i]
        for j in range(i + 1, len(tokenized)):
            lj, tj = tokenized[j]
            if li.source == lj.source:
                continue
            sim = _jaccard_similarity(ti, tj)
            if sim > 0.0:
                pairs.append((sim, li, lj))

    if not pairs:
        print("  No cross-source pairs share any tokens at all.")
        print("  Likely the two sources are featuring disjoint product categories")
        print("  right now. Adding more sources (Woot, BensBargains) would help.")
        print()
        return

    pairs.sort(reverse=True, key=lambda p: p[0])
    top = pairs[:top_n]
    for sim, a, b in top:
        print(f"  [{sim:.2f}]  {a.source:10}  {a.title[:70]}")
        print(f"          {b.source:10}  {b.title[:70]}")
        print()


if __name__ == "__main__":
    main()
