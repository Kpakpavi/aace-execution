"""Unit tests for the resale-comps connector.

Covers:
  * MockResaleCompsClient is deterministic + obeys its band
  * KeepaClient / SerpApiClient raise NotImplementedError as stubs
  * RoutedResaleCompsClient picks the right backend per platform
  * Router transparently falls back when the primary backend raises
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aace_execution.connectors.resale_comps import (
    KeepaClient,
    MockResaleCompsClient,
    ResaleComp,
    RoutedResaleCompsClient,
    SerpApiClient,
)


# ---------------------------------------------------------------------------
# MockResaleCompsClient
# ---------------------------------------------------------------------------


class TestMockResaleCompsClient:
    def test_returns_comp_with_required_fields(self):
        client = MockResaleCompsClient()
        comp = client.lookup(
            product_key="apple watch series 11",
            platform="Amazon",
            price_hint=266.0,
        )
        assert comp is not None
        assert comp.product_key == "apple watch series 11"
        assert comp.platform == "Amazon"
        assert comp.sold_avg > 0
        assert comp.sold_count >= 5
        assert comp.source == "mock"
        assert 0.0 <= comp.confidence <= 1.0

    def test_deterministic_for_same_product_key(self):
        client = MockResaleCompsClient()
        a = client.lookup(product_key="foo bar", platform="Amazon", price_hint=100.0)
        b = client.lookup(product_key="foo bar", platform="Amazon", price_hint=100.0)
        assert a.sold_avg == b.sold_avg
        assert a.sold_count == b.sold_count

    def test_different_keys_give_different_results(self):
        client = MockResaleCompsClient()
        a = client.lookup(product_key="alpha", platform="Amazon", price_hint=100.0)
        b = client.lookup(product_key="beta", platform="Amazon", price_hint=100.0)
        # SHA1 of "alpha" vs "beta" differs in byte 0 - markup wiggle differs
        assert a.sold_avg != b.sold_avg or a.sold_count != b.sold_count

    def test_markup_is_within_band(self):
        # Per docstring, markup ranges over default ± [-0.10, +0.30]
        # With default_markup_pct=0.18, sold_avg/price_hint must be in
        # [1.08, 1.48].
        client = MockResaleCompsClient(default_markup_pct=0.18)
        price = 100.0
        for key in ("a", "ab", "abc", "x" * 10, "macbook air m3 256gb"):
            comp = client.lookup(product_key=key, platform="Amazon", price_hint=price)
            ratio = comp.sold_avg / price
            assert 1.08 <= ratio <= 1.48, (
                f"key {key!r} produced ratio {ratio} outside [1.08, 1.48]"
            )

    def test_no_price_hint_falls_back_to_50(self):
        client = MockResaleCompsClient()
        comp = client.lookup(product_key="thing", platform="eBay", price_hint=None)
        # Baseline $50, markup band [1.08, 1.48] -> sold_avg in [54, 74]
        assert 54.0 <= comp.sold_avg <= 74.0
        assert comp.extra["baseline"] == 50.0

    def test_zero_price_hint_falls_back(self):
        client = MockResaleCompsClient()
        comp = client.lookup(product_key="thing", platform="eBay", price_hint=0.0)
        assert comp.extra["baseline"] == 50.0

    def test_invalid_default_markup_rejected(self):
        with pytest.raises(ValueError):
            MockResaleCompsClient(default_markup_pct=-0.1)
        with pytest.raises(ValueError):
            MockResaleCompsClient(default_markup_pct=1.5)


# ---------------------------------------------------------------------------
# Stub clients
# ---------------------------------------------------------------------------


class TestStubClients:
    def test_keepa_requires_api_key(self):
        with pytest.raises(ValueError):
            KeepaClient(api_key="")

    def test_keepa_constructs_real_client(self):
        # KeepaClient is no longer a stub — it has a real implementation.
        # Per-method behavior is covered exhaustively in
        # tests/test_keepa_client.py (or smoke_keepa_client.py under
        # outputs/) with an injected fake http client.
        client = KeepaClient(api_key="test-key")
        assert client.name == "keepa"

    def test_serpapi_requires_api_key(self):
        with pytest.raises(ValueError):
            SerpApiClient(api_key="")

    def test_serpapi_lookup_is_stub(self):
        client = SerpApiClient(api_key="test-key")
        with pytest.raises(NotImplementedError):
            client.lookup(
                product_key="x", platform="eBay", price_hint=100.0
            )


# ---------------------------------------------------------------------------
# RoutedResaleCompsClient
# ---------------------------------------------------------------------------


def _stub_client(name: str, *, returns: ResaleComp | None = None, raises: Exception | None = None):
    """Return a mock that satisfies the ResaleCompsClient protocol."""
    m = MagicMock()
    m.name = name
    if raises is not None:
        m.lookup.side_effect = raises
    else:
        m.lookup.return_value = returns
    return m


def _mk_comp(source: str, sold_avg: float = 200.0) -> ResaleComp:
    from datetime import datetime, timezone
    return ResaleComp(
        product_key="x",
        platform="Amazon",
        sold_avg=sold_avg,
        sold_count=10,
        source=source,
        observed_at=datetime.now(timezone.utc),
        confidence=0.5,
    )


class TestRoutedResaleCompsClient:
    def test_amazon_routes_to_keepa(self):
        keepa = _stub_client("keepa", returns=_mk_comp("keepa", 250.0))
        serpapi = _stub_client("serpapi", returns=_mk_comp("serpapi", 999.0))
        router = RoutedResaleCompsClient(keepa=keepa, serpapi=serpapi)

        comp = router.lookup(product_key="x", platform="Amazon", price_hint=100.0)

        assert comp.source == "keepa"
        keepa.lookup.assert_called_once()
        serpapi.lookup.assert_not_called()

    def test_non_amazon_routes_to_serpapi(self):
        keepa = _stub_client("keepa", returns=_mk_comp("keepa", 999.0))
        serpapi = _stub_client("serpapi", returns=_mk_comp("serpapi", 150.0))
        router = RoutedResaleCompsClient(keepa=keepa, serpapi=serpapi)

        comp = router.lookup(product_key="x", platform="eBay", price_hint=100.0)

        assert comp.source == "serpapi"
        serpapi.lookup.assert_called_once()
        keepa.lookup.assert_not_called()

    def test_no_primary_configured_uses_fallback(self):
        fallback = MockResaleCompsClient()
        router = RoutedResaleCompsClient(fallback=fallback)
        # No keepa / serpapi configured - everything goes to fallback
        comp_amzn = router.lookup(product_key="x", platform="Amazon", price_hint=100.0)
        comp_ebay = router.lookup(product_key="x", platform="eBay", price_hint=100.0)
        assert comp_amzn.source == "mock"
        assert comp_ebay.source == "mock"

    def test_primary_notimplemented_falls_back(self):
        # KeepaClient's stub raises NotImplementedError - router must catch and
        # fall back so the worker keeps moving while real Keepa is being wired.
        keepa = _stub_client("keepa", raises=NotImplementedError("stub"))
        fallback = MockResaleCompsClient()
        router = RoutedResaleCompsClient(keepa=keepa, fallback=fallback)

        comp = router.lookup(product_key="x", platform="Amazon", price_hint=100.0)

        assert comp.source == "mock"
        keepa.lookup.assert_called_once()

    def test_primary_runtime_error_falls_back(self):
        # Any unexpected exception from a real primary client (network down,
        # quota exceeded, malformed response) must NOT crash the tick.
        keepa = _stub_client("keepa", raises=RuntimeError("HTTP 500"))
        fallback = MockResaleCompsClient()
        router = RoutedResaleCompsClient(keepa=keepa, fallback=fallback)

        comp = router.lookup(product_key="x", platform="Amazon", price_hint=100.0)

        assert comp.source == "mock"

    def test_default_fallback_is_mock(self):
        # When no fallback is supplied, router must default to MockResaleCompsClient.
        router = RoutedResaleCompsClient()
        comp = router.lookup(product_key="x", platform="Amazon", price_hint=100.0)
        assert comp.source == "mock"

    def test_router_advertises_name(self):
        router = RoutedResaleCompsClient()
        assert router.name == "routed"
