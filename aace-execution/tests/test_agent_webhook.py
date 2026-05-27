"""Unit tests for the AI-agent outbound webhook.

Network is fully mocked. ``time.sleep`` is fully mocked (via injectable
``sleep_fn``). Tests run in milliseconds and are deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from aace_execution.integrations.agent_webhook import (
    AgentWebhookClient,
    InMemoryWebhookDedupStore,
    WebhookPayload,
    sign_payload,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)


def _mk_payload(opportunity_id: str = "opp-001") -> WebhookPayload:
    return WebhookPayload(
        opportunity_id=opportunity_id,
        product_key="apple macbook air m3",
        sources=["slickdeals", "dealnews"],
        listings=[
            {"source": "slickdeals", "price": 799.0, "url": "https://s.example/1"},
            {"source": "dealnews", "price": 749.0, "url": "https://d.example/2"},
        ],
        score=0.92,
        detected_at=_FIXED_NOW,
        metadata={"matcher_version": "v1"},
    )


def _mk_http_response(status_code: int = 200, text: str = "ok"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def _stub_http(status_code: int = 200, text: str = "ok"):
    """httpx.Client stand-in that returns one fixed response."""
    client = MagicMock()
    client.post = MagicMock(return_value=_mk_http_response(status_code, text))
    return client


class _NoSleep:
    """Captures sleep durations without actually sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ---------------------------------------------------------------------------
# sign_payload()
# ---------------------------------------------------------------------------


class TestSignPayload:
    def test_returns_sha256_prefixed_hex(self):
        sig = sign_payload("secret", b'{"hello":"world"}')
        assert sig.startswith("sha256=")
        digest = sig.split("=", 1)[1]
        assert len(digest) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in digest)

    def test_deterministic_for_same_input(self):
        a = sign_payload("secret", b'{"x":1}')
        b = sign_payload("secret", b'{"x":1}')
        assert a == b

    def test_different_secret_yields_different_signature(self):
        a = sign_payload("secret1", b'{"x":1}')
        b = sign_payload("secret2", b'{"x":1}')
        assert a != b

    def test_different_body_yields_different_signature(self):
        a = sign_payload("secret", b'{"x":1}')
        b = sign_payload("secret", b'{"x":2}')
        assert a != b


# ---------------------------------------------------------------------------
# Happy path delivery
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_delivers_on_first_attempt(self):
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=_stub_http(200)
        )
        result = client.send(_mk_payload())
        assert result.status == "delivered"
        assert result.attempts == 1
        assert result.last_status_code == 200
        assert result.delivered_at is not None

    def test_posts_to_configured_url(self):
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        client.send(_mk_payload())
        url_arg = http.post.call_args[0][0]
        assert url_arg == "https://agent.example/hook"

    def test_includes_hmac_signature_header(self):
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        client.send(_mk_payload())
        headers = http.post.call_args[1]["headers"]
        assert "X-AACE-Signature" in headers
        assert headers["X-AACE-Signature"].startswith("sha256=")

    def test_includes_content_type_json(self):
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        client.send(_mk_payload())
        headers = http.post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_signature_matches_body(self):
        """The signature on the wire must verify against the actual body bytes."""
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        client.send(_mk_payload())
        body = http.post.call_args[1]["content"]
        sent_sig = http.post.call_args[1]["headers"]["X-AACE-Signature"]
        assert sent_sig == sign_payload("shh", body)

    def test_body_is_valid_json(self):
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        client.send(_mk_payload(opportunity_id="opp-xyz"))
        body = http.post.call_args[1]["content"]
        parsed = json.loads(body)
        assert parsed["opportunity_id"] == "opp-xyz"
        assert parsed["product_key"] == "apple macbook air m3"
        assert parsed["score"] == 0.92

    def test_datetime_serialized_as_iso8601(self):
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        client.send(_mk_payload())
        body = http.post.call_args[1]["content"]
        parsed = json.loads(body)
        assert "2026-05-28T12:00:00+00:00" in parsed["detected_at"]


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


class TestDedup:
    def test_second_send_within_window_is_deduped(self):
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        first = client.send(_mk_payload("opp-1"))
        second = client.send(_mk_payload("opp-1"))
        assert first.status == "delivered"
        assert second.status == "deduped"
        assert second.attempts == 0
        # Only one actual HTTP POST went out
        assert http.post.call_count == 1

    def test_different_opportunity_ids_not_deduped(self):
        http = _stub_http(200)
        client = AgentWebhookClient(
            "https://agent.example/hook", "shh", http_client=http
        )
        client.send(_mk_payload("opp-1"))
        result = client.send(_mk_payload("opp-2"))
        assert result.status == "delivered"
        assert http.post.call_count == 2


class TestInMemoryDedupStore:
    def test_unseen_id_is_not_recently_sent(self):
        store = InMemoryWebhookDedupStore()
        assert not store.was_recently_sent("opp-1")

    def test_marked_id_is_recently_sent(self):
        store = InMemoryWebhookDedupStore()
        store.mark_sent("opp-1", status_code=200, attempts=1)
        assert store.was_recently_sent("opp-1")

    def test_outside_window_not_recently_sent(self):
        store = InMemoryWebhookDedupStore()
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        store.mark_sent("opp-1", status_code=200, attempts=1, when=old)
        assert not store.was_recently_sent("opp-1", within_hours=24)

    def test_inside_wider_window_still_recently_sent(self):
        store = InMemoryWebhookDedupStore()
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        store.mark_sent("opp-1", status_code=200, attempts=1, when=old)
        assert store.was_recently_sent("opp-1", within_hours=26)


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


class TestRetry:
    def test_retries_on_5xx_until_success(self):
        responses = [_mk_http_response(503, "busy"), _mk_http_response(200, "ok")]
        http = MagicMock()
        http.post = MagicMock(side_effect=responses)
        sleeper = _NoSleep()
        client = AgentWebhookClient(
            "https://agent.example/hook",
            "shh",
            http_client=http,
            sleep_fn=sleeper,
        )
        result = client.send(_mk_payload())
        assert result.status == "delivered"
        assert result.attempts == 2
        assert sleeper.calls == [1.0]  # one backoff between two attempts

    def test_retries_on_429_rate_limit(self):
        responses = [_mk_http_response(429, ""), _mk_http_response(200, "ok")]
        http = MagicMock()
        http.post = MagicMock(side_effect=responses)
        sleeper = _NoSleep()
        client = AgentWebhookClient(
            "https://agent.example/hook",
            "shh",
            http_client=http,
            sleep_fn=sleeper,
        )
        result = client.send(_mk_payload())
        assert result.status == "delivered"
        assert result.attempts == 2

    def test_does_not_retry_on_4xx_non_429(self):
        http = MagicMock()
        http.post = MagicMock(return_value=_mk_http_response(401, "auth fail"))
        sleeper = _NoSleep()
        client = AgentWebhookClient(
            "https://agent.example/hook",
            "shh",
            http_client=http,
            sleep_fn=sleeper,
        )
        result = client.send(_mk_payload())
        assert result.status == "failed"
        assert result.attempts == 1
        assert http.post.call_count == 1
        assert sleeper.calls == []

    def test_retries_on_network_exception(self):
        responses = [ConnectionError("dns boom"), _mk_http_response(200, "ok")]
        http = MagicMock()
        http.post = MagicMock(side_effect=responses)
        sleeper = _NoSleep()
        client = AgentWebhookClient(
            "https://agent.example/hook",
            "shh",
            http_client=http,
            sleep_fn=sleeper,
        )
        result = client.send(_mk_payload())
        assert result.status == "delivered"
        assert result.attempts == 2

    def test_gives_up_after_max_attempts(self):
        http = MagicMock()
        http.post = MagicMock(return_value=_mk_http_response(503, "busy"))
        sleeper = _NoSleep()
        client = AgentWebhookClient(
            "https://agent.example/hook",
            "shh",
            http_client=http,
            sleep_fn=sleeper,
            max_attempts=4,
            backoff_seconds=(1.0, 5.0, 30.0, 300.0),
        )
        result = client.send(_mk_payload())
        assert result.status == "failed"
        assert result.attempts == 4
        assert http.post.call_count == 4
        # 3 backoffs between 4 attempts (no sleep after the last)
        assert sleeper.calls == [1.0, 5.0, 30.0]

    def test_failed_delivery_not_marked_in_dedup(self):
        """A failed delivery must NOT block a retry on the next tick."""
        http = MagicMock()
        http.post = MagicMock(return_value=_mk_http_response(503, "busy"))
        sleeper = _NoSleep()
        store = InMemoryWebhookDedupStore()
        client = AgentWebhookClient(
            "https://agent.example/hook",
            "shh",
            http_client=http,
            sleep_fn=sleeper,
            dedup_store=store,
        )
        client.send(_mk_payload("opp-1"))
        assert not store.was_recently_sent("opp-1")


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_empty_url_rejected(self):
        with pytest.raises(ValueError):
            AgentWebhookClient("", "secret")

    def test_empty_secret_rejected(self):
        with pytest.raises(ValueError):
            AgentWebhookClient("https://x", "")

    def test_zero_max_attempts_rejected(self):
        with pytest.raises(ValueError):
            AgentWebhookClient("https://x", "secret", max_attempts=0)
