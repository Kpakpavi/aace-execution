"""Local demo with a synthetic match — proves the end-to-end pipeline.

Real-world cross-source matching is brittle in v0.1.0 (the matcher
uses a simple lowercase + alphanumeric title key; small differences
like "for" vs no "for" produce different keys). Improving the key
strategy is post-v0.1.0 work.

This demo bypasses the live RSS fetches and injects two pre-matched
listings (same product, two different sources, $100 price gap) so you
can see the matcher → scorer → webhook chain actually deliver to your
webhook.site URL.

Usage:

    AGENT_WEBHOOK_URL="https://webhook.site/<your-id>" \\
    uv run python scripts/demo_synthetic_match.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


def _ensure_ssl_certs() -> None:
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

    from aace_execution.connectors.base import NormalizedListing
    from aace_execution.integrations.agent_webhook import AgentWebhookClient
    from aace_execution.pipeline.cross_source_matcher import match_cross_source
    from aace_execution.pipeline.opportunity_scorer import OpportunityScorer
    from aace_execution.worker import _build_webhook_payload

    now = datetime.now(timezone.utc)

    # Two synthetic listings for the SAME product on two DIFFERENT sources.
    # In production these would come from real connector runs.
    listings = [
        NormalizedListing(
            source="slickdeals",
            listing_id="slickdeals:demo-mba-1",
            external_id="demo-mba-1",
            product_key="apple macbook air m3 256gb",
            title='Apple MacBook Air 13" M3 256GB $799 + Free Shipping',
            url="https://slickdeals.net/f/demo-1",
            price=799.0,
            currency="USD",
            observed_at=now,
        ),
        NormalizedListing(
            source="dealnews",
            listing_id="dealnews:demo-mba-2",
            external_id="demo-mba-2",
            product_key="apple macbook air m3 256gb",
            title="Apple MacBook Air M3 256GB $899 at Best Buy",
            url="https://www.dealnews.com/demo-2",
            price=899.0,
            currency="USD",
            observed_at=now,
        ),
    ]

    bar = "=" * 64
    print()
    print(bar)
    print("AACE synthetic demo  -  two pre-matched listings")
    print(bar)
    print()

    print("Synthetic input (no live fetch this run):")
    for listing in listings:
        print(f"  {listing.source:12} ${listing.price:>7.2f}  {listing.title}")
    print()

    groups = match_cross_source(listings)
    print(f"Cross-source match groups: {len(groups)}")
    for group in groups:
        print(
            f"  - {group.product_key}  "
            f"({group.source_count} sources, {group.listing_count} listings)"
        )
    print()

    scorer = OpportunityScorer()
    scored = [scorer.score(g) for g in groups]
    scored = [opp for opp in scored if opp is not None]

    print(f"Above-threshold opportunities: {len(scored)}")
    for opp in scored:
        print(
            f"  - {opp.product_key}  "
            f"spread ${opp.absolute_spread:.2f} ({opp.percent_spread * 100:.1f}%)  "
            f"score {opp.score:.3f}"
        )
    print()

    if not scored:
        print("Nothing to ship.")
        return

    print("Shipping to webhook...")
    client = AgentWebhookClient(
        webhook_url=os.environ["AGENT_WEBHOOK_URL"],
        webhook_secret=os.environ["AGENT_WEBHOOK_SECRET"],
    )
    for opp in scored:
        payload = _build_webhook_payload(opp)
        result = client.send(payload)
        detail = (
            f"status={result.last_status_code}"
            if result.last_status_code is not None
            else (result.last_error or "no response")
        )
        print(
            f"  [{result.status:>9}]  {opp.product_key:<40}  "
            f"{result.attempts} attempt(s)  {detail}"
        )
    print()
    print(bar)
    print("Refresh your webhook.site tab. You should see a signed POST")
    print("with the full JSON payload + X-AACE-Signature header.")
    print(bar)
    print()


if __name__ == "__main__":
    main()
