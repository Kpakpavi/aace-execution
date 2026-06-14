"""Unit tests for the email digest integration."""

from __future__ import annotations

from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from unittest.mock import MagicMock

import pytest

from aace_execution.integrations.email_digest import (
    EmailDigest,
    EmailDigestResult,
    _RankedRow,
    _html_escape,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 6, 11, 7, 0, tzinfo=timezone.utc)


def _stub_smtp_factory(raises: Exception | None = None):
    """Return a factory matching ``_default_smtp_factory``'s signature."""
    sent_messages: list[MIMEMultipart] = []
    auth_calls: list[tuple[str, str]] = []
    client = MagicMock()

    def _login(user, pwd):
        auth_calls.append((user, pwd))

    def _send_message(msg):
        if raises is not None:
            raise raises
        sent_messages.append(msg)

    client.login = MagicMock(side_effect=_login)
    client.send_message = MagicMock(side_effect=_send_message)
    client.ehlo = MagicMock()
    client.starttls = MagicMock()
    client.quit = MagicMock()

    def factory(*, host, port):
        return client

    factory.client = client
    factory.sent_messages = sent_messages
    factory.auth_calls = auth_calls
    return factory


def _mk_kwargs(**overrides):
    """Minimal valid constructor kwargs."""
    base = dict(
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_username="me@example.com",
        smtp_app_password="x" * 16,
        from_addr="me@example.com",
        to_addrs=["manager@example.com"],
        min_net_profit=0.0,
        min_roi_percent=0.0,
        smtp_client_factory=_stub_smtp_factory(),
    )
    base.update(overrides)
    return base


# Apple Watch — buy $266, resale $329 → eBay fee $43.59 + $8 ship → net $11.41 / 4.3% ROI
def _mk_opp(min_p=266.0, max_p=329.0, product_key="apple watch series 11", sources="slickdeals,techbargains"):
    return {
        "opportunity_id": f"opp-{product_key}",
        "product_key": product_key,
        "sources": sources,
        "min_price": min_p,
        "max_price": max_p,
        "absolute_spread": max_p - min_p,
        "detected_at": "2026-06-11T05:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    @pytest.mark.parametrize("field,bad_value", [
        ("smtp_host", ""),
        ("smtp_username", ""),
        ("smtp_app_password", ""),
        ("from_addr", ""),
    ])
    def test_empty_string_fields_rejected(self, field, bad_value):
        kw = _mk_kwargs(**{field: bad_value})
        with pytest.raises(ValueError):
            EmailDigest(**kw)

    def test_empty_to_addrs_rejected(self):
        with pytest.raises(ValueError):
            EmailDigest(**_mk_kwargs(to_addrs=[]))

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 100000])
    def test_invalid_port_rejected(self, bad_port):
        with pytest.raises(ValueError):
            EmailDigest(**_mk_kwargs(smtp_port=bad_port))

    def test_negative_min_net_profit_rejected(self):
        with pytest.raises(ValueError):
            EmailDigest(**_mk_kwargs(min_net_profit=-0.01))

    def test_negative_min_roi_rejected(self):
        with pytest.raises(ValueError):
            EmailDigest(**_mk_kwargs(min_roi_percent=-0.01))

    def test_top_n_below_one_rejected(self):
        with pytest.raises(ValueError):
            EmailDigest(**_mk_kwargs(top_n=0))

    def test_lookback_below_one_rejected(self):
        with pytest.raises(ValueError):
            EmailDigest(**_mk_kwargs(lookback_hours=0))


# ---------------------------------------------------------------------------
# from_environment
# ---------------------------------------------------------------------------


class TestFromEnvironment:
    def test_disabled_when_host_missing(self):
        assert EmailDigest.from_environment(env={
            "EMAIL_USERNAME": "u", "EMAIL_APP_PASSWORD": "p",
            "EMAIL_TO": "a@b.c",
        }) is None

    def test_disabled_when_username_missing(self):
        assert EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "h", "EMAIL_APP_PASSWORD": "p",
            "EMAIL_TO": "a@b.c",
        }) is None

    def test_disabled_when_password_missing(self):
        assert EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "h", "EMAIL_USERNAME": "u",
            "EMAIL_TO": "a@b.c",
        }) is None

    def test_disabled_when_to_missing(self):
        assert EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "h", "EMAIL_USERNAME": "u",
            "EMAIL_APP_PASSWORD": "p",
        }) is None

    def test_builds_with_required_fields(self):
        d = EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "smtp.gmail.com",
            "EMAIL_USERNAME": "me@gmail.com",
            "EMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
            "EMAIL_TO": "manager@example.com",
        })
        assert d is not None

    def test_parses_multiple_to_addrs(self):
        d = EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "h", "EMAIL_USERNAME": "u",
            "EMAIL_APP_PASSWORD": "p",
            "EMAIL_TO": "a@x.com, b@x.com ,c@x.com",
        })
        assert d._to_addrs == ["a@x.com", "b@x.com", "c@x.com"]

    def test_bad_port_falls_back_to_465(self):
        d = EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "h", "EMAIL_USERNAME": "u",
            "EMAIL_APP_PASSWORD": "p", "EMAIL_TO": "a@b.c",
            "EMAIL_SMTP_PORT": "not_a_port",
        })
        assert d._smtp_port == 465

    def test_from_addr_defaults_to_username(self):
        d = EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "h",
            "EMAIL_USERNAME": "me@gmail.com",
            "EMAIL_APP_PASSWORD": "p", "EMAIL_TO": "a@b.c",
        })
        assert d._from_addr == "me@gmail.com"

    def test_bad_top_n_falls_back_to_default(self):
        d = EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "h", "EMAIL_USERNAME": "u",
            "EMAIL_APP_PASSWORD": "p", "EMAIL_TO": "a@b.c",
            "EMAIL_DIGEST_TOP_N": "garbage",
        })
        assert d._top_n == 10


# ---------------------------------------------------------------------------
# Filtering and ranking
# ---------------------------------------------------------------------------


class TestFilterAndRank:
    def test_skips_when_no_qualifying_opportunities(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(
            min_net_profit=100.0,  # too tight
            smtp_client_factory=factory,
        ))
        result = d.send_digest([_mk_opp()], now=_NOW)
        assert result.status == "skipped"
        assert result.reason == "no_qualifying_opportunities"
        assert factory.client.send_message.call_count == 0

    def test_filters_below_net_floor(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(
            min_net_profit=20.0,
            smtp_client_factory=factory,
        ))
        # Apple watch: net = 11.41 → below 20 floor
        result = d.send_digest([_mk_opp()], now=_NOW)
        assert result.status == "skipped"

    def test_filters_below_roi_floor(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(
            min_roi_percent=10.0,
            smtp_client_factory=factory,
        ))
        # Apple watch: ROI ~ 4.3% → below 10 floor
        result = d.send_digest([_mk_opp()], now=_NOW)
        assert result.status == "skipped"

    def test_top_n_truncates_results(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(top_n=2, smtp_client_factory=factory))
        opps = [
            _mk_opp(min_p=20.0, max_p=80.0, product_key="a"),
            _mk_opp(min_p=20.0, max_p=70.0, product_key="b"),
            _mk_opp(min_p=20.0, max_p=60.0, product_key="c"),
            _mk_opp(min_p=20.0, max_p=50.0, product_key="d"),
        ]
        result = d.send_digest(opps, now=_NOW)
        assert result.status == "sent"
        assert result.deal_count == 2

    def test_sorted_by_net_profit_descending(self):
        # Build with the public API and inspect the resulting plain text
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        opps = [
            _mk_opp(min_p=20.0, max_p=60.0, product_key="low margin"),
            _mk_opp(min_p=20.0, max_p=100.0, product_key="big margin"),
            _mk_opp(min_p=20.0, max_p=80.0, product_key="mid margin"),
        ]
        d.send_digest(opps, now=_NOW)
        sent = factory.sent_messages[0]
        plain_part = next(p for p in sent.walk() if p.get_content_type() == "text/plain")
        body = plain_part.get_payload(decode=True).decode("utf-8")
        # "big margin" should appear before "mid margin" before "low margin"
        assert body.index("Big Margin") < body.index("Mid Margin") < body.index("Low Margin")

    def test_zero_or_negative_prices_skipped(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        opps = [
            _mk_opp(min_p=0.0, max_p=100.0),       # zero buy
            _mk_opp(min_p=20.0, max_p=0.0),         # zero resale
            _mk_opp(min_p=20.0, max_p=100.0, product_key="good"),  # valid
        ]
        d.send_digest(opps, now=_NOW)
        # Only the valid one should be in the body
        sent = factory.sent_messages[0]
        plain = next(p for p in sent.walk() if p.get_content_type() == "text/plain")
        body = plain.get_payload(decode=True).decode("utf-8")
        assert "Good" in body

    def test_malformed_rows_silently_dropped(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        opps = [
            {"product_key": "nope", "min_price": "not-a-number"},  # bad
            _mk_opp(min_p=20.0, max_p=100.0, product_key="good"),  # valid
        ]
        result = d.send_digest(opps, now=_NOW)
        assert result.status == "sent"
        assert result.deal_count == 1


# ---------------------------------------------------------------------------
# Message structure
# ---------------------------------------------------------------------------


class TestMessageStructure:
    def test_subject_includes_deal_count_and_lookback(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        sent = factory.sent_messages[0]
        assert "1 profitable deals" in sent["Subject"]
        assert "24h" in sent["Subject"]

    def test_from_and_to_set_correctly(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(
            from_addr="aace@example.com",
            to_addrs=["manager@example.com", "lead@example.com"],
            smtp_client_factory=factory,
        ))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        sent = factory.sent_messages[0]
        assert sent["From"] == "aace@example.com"
        assert sent["To"] == "manager@example.com, lead@example.com"

    def test_message_is_multipart_with_plain_and_html(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        sent = factory.sent_messages[0]
        types = {p.get_content_type() for p in sent.walk()}
        assert "text/plain" in types
        assert "text/html" in types

    def test_html_body_contains_product_and_net(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0,
                                product_key="apple watch")], now=_NOW)
        sent = factory.sent_messages[0]
        html_part = next(p for p in sent.walk() if p.get_content_type() == "text/html")
        body = html_part.get_payload(decode=True).decode("utf-8")
        assert "Apple Watch" in body
        assert "$20.00" in body
        assert "$100.00" in body

    def test_plain_body_contains_same_product(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0,
                                product_key="apple watch")], now=_NOW)
        sent = factory.sent_messages[0]
        plain_part = next(p for p in sent.walk() if p.get_content_type() == "text/plain")
        body = plain_part.get_payload(decode=True).decode("utf-8")
        assert "Apple Watch" in body
        assert "$20.00" in body


# ---------------------------------------------------------------------------
# SMTP wiring
# ---------------------------------------------------------------------------


class TestSmtpWiring:
    def test_logs_in_with_provided_credentials(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(
            smtp_username="me@gmail.com",
            smtp_app_password="abcdefghijklmnop",
            smtp_client_factory=factory,
        ))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        assert factory.auth_calls == [("me@gmail.com", "abcdefghijklmnop")]

    def test_port_587_triggers_starttls(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(
            smtp_port=587, smtp_client_factory=factory,
        ))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        # STARTTLS path: ehlo → starttls → ehlo
        assert factory.client.starttls.call_count == 1
        assert factory.client.ehlo.call_count == 2

    def test_port_465_skips_starttls(self):
        factory = _stub_smtp_factory()
        d = EmailDigest(**_mk_kwargs(
            smtp_port=465, smtp_client_factory=factory,
        ))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        # Implicit-TLS path: no STARTTLS, no extra ehlo
        assert factory.client.starttls.call_count == 0


# ---------------------------------------------------------------------------
# Failure tolerance — NEVER crash the scheduled job
# ---------------------------------------------------------------------------


class TestFailureTolerance:
    def test_smtp_failure_returns_failed_result(self):
        factory = _stub_smtp_factory(raises=ConnectionError("smtp down"))
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        result = d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        assert result.status == "failed"
        assert "ConnectionError" in (result.reason or "")

    def test_smtp_auth_failure_returns_failed(self):
        import smtplib
        factory = _stub_smtp_factory(
            raises=smtplib.SMTPAuthenticationError(535, b"bad password")
        )
        d = EmailDigest(**_mk_kwargs(smtp_client_factory=factory))
        result = d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        assert result.status == "failed"
        assert "SMTPAuthenticationError" in (result.reason or "")


# ---------------------------------------------------------------------------
# Mandrill transport
# ---------------------------------------------------------------------------


def _stub_mandrill_http(*, status: int = 200, raises: Exception | None = None,
                        body=None):
    """HTTP client double that satisfies the Mandrill caller's contract."""
    client = MagicMock()
    if raises is not None:
        client.post.side_effect = raises
        return client
    resp = MagicMock()
    resp.status_code = status
    if status >= 400:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(
            f"HTTP {status}", response=resp
        )
    else:
        resp.raise_for_status = MagicMock()
    # Mandrill returns a list of recipient delivery results
    if body is None:
        body = [{"email": "a@b.c", "status": "sent", "_id": "x"}]
    resp.json = MagicMock(return_value=body)
    client.post.return_value = resp
    return client


def _mandrill_kwargs(**overrides):
    """Mandrill-mode kwargs — no SMTP fields needed."""
    base = dict(
        from_addr="aace@example.com",
        to_addrs=["manager@example.com"],
        min_net_profit=0.0,
        min_roi_percent=0.0,
        mandrill_api_key="md-test-key",
        mandrill_from_name="AACE",
        mandrill_http_client=_stub_mandrill_http(),
    )
    base.update(overrides)
    return base


class TestMandrillTransport:
    def test_uses_mandrill_when_api_key_present(self):
        http = _stub_mandrill_http()
        d = EmailDigest(**_mandrill_kwargs(mandrill_http_client=http))
        result = d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        assert result.status == "sent"
        http.post.assert_called_once()
        url_posted = http.post.call_args[0][0]
        assert url_posted == "https://mandrillapp.com/api/1.0/messages/send.json"

    def test_payload_includes_api_key_and_recipients(self):
        http = _stub_mandrill_http()
        d = EmailDigest(**_mandrill_kwargs(
            mandrill_api_key="md-secret-xyz",
            to_addrs=["a@x.com", "b@x.com"],
            mandrill_http_client=http,
        ))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        payload = http.post.call_args[1]["json"]
        assert payload["key"] == "md-secret-xyz"
        assert payload["message"]["to"] == [
            {"email": "a@x.com", "type": "to"},
            {"email": "b@x.com", "type": "to"},
        ]

    def test_payload_carries_from_and_subject_and_bodies(self):
        http = _stub_mandrill_http()
        d = EmailDigest(**_mandrill_kwargs(
            from_addr="aace@example.com",
            mandrill_from_name="AACE Deals",
            mandrill_http_client=http,
        ))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        msg = http.post.call_args[1]["json"]["message"]
        assert msg["from_email"] == "aace@example.com"
        assert msg["from_name"] == "AACE Deals"
        assert "profitable deals" in msg["subject"]
        assert "<html>" in msg["html"].lower() or "<table" in msg["html"]
        assert "AACE Daily Digest" in msg["text"]
        assert "aace" in msg["tags"]
        assert "daily-digest" in msg["tags"]

    def test_smtp_path_not_taken_when_mandrill_set(self):
        smtp = _stub_smtp_factory()
        http = _stub_mandrill_http()
        d = EmailDigest(**_mandrill_kwargs(
            smtp_client_factory=smtp,
            mandrill_http_client=http,
        ))
        d.send_digest([_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW)
        assert smtp.client.send_message.call_count == 0
        assert http.post.call_count == 1

    def test_mandrill_http_error_returns_failed(self):
        http = _stub_mandrill_http(status=500)
        d = EmailDigest(**_mandrill_kwargs(mandrill_http_client=http))
        result = d.send_digest(
            [_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW
        )
        assert result.status == "failed"
        assert "mandrill_error" in (result.reason or "")

    def test_mandrill_rejected_recipients_returns_failed(self):
        # Every recipient bounced — Mandrill returns "rejected" status
        http = _stub_mandrill_http(body=[
            {"email": "a@b.c", "status": "rejected", "reject_reason": "spam"},
        ])
        d = EmailDigest(**_mandrill_kwargs(mandrill_http_client=http))
        result = d.send_digest(
            [_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW
        )
        assert result.status == "failed"

    def test_mandrill_queued_status_still_counts_as_success(self):
        # "queued" is a legitimate Mandrill outcome for high-volume sends
        http = _stub_mandrill_http(body=[
            {"email": "a@b.c", "status": "queued"},
        ])
        d = EmailDigest(**_mandrill_kwargs(mandrill_http_client=http))
        result = d.send_digest(
            [_mk_opp(min_p=20.0, max_p=100.0)], now=_NOW
        )
        assert result.status == "sent"


class TestMandrillFromEnvironment:
    def test_mandrill_key_alone_disables_when_no_to(self):
        d = EmailDigest.from_environment(env={
            "MANDRILL_API_KEY": "md-xxx",
        })
        assert d is None

    def test_mandrill_path_when_smtp_absent_but_key_set(self):
        d = EmailDigest.from_environment(env={
            "MANDRILL_API_KEY": "md-xxx",
            "EMAIL_TO": "a@b.c",
            "EMAIL_FROM": "from@b.c",
        })
        assert d is not None
        assert d._use_mandrill is True

    def test_mandrill_wins_when_both_configured(self):
        d = EmailDigest.from_environment(env={
            "MANDRILL_API_KEY": "md-xxx",
            "EMAIL_SMTP_HOST": "smtp.gmail.com",
            "EMAIL_USERNAME": "me@gmail.com",
            "EMAIL_APP_PASSWORD": "p",
            "EMAIL_TO": "a@b.c",
        })
        assert d is not None
        assert d._use_mandrill is True

    def test_smtp_path_when_only_smtp_configured(self):
        d = EmailDigest.from_environment(env={
            "EMAIL_SMTP_HOST": "smtp.gmail.com",
            "EMAIL_USERNAME": "me@gmail.com",
            "EMAIL_APP_PASSWORD": "p",
            "EMAIL_TO": "a@b.c",
        })
        assert d is not None
        assert d._use_mandrill is False


# ---------------------------------------------------------------------------
# HTML escape helper
# ---------------------------------------------------------------------------


class TestHtmlEscape:
    @pytest.mark.parametrize("raw,expected", [
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ("Tom & Jerry", "Tom &amp; Jerry"),
        ('She said "hi"', "She said &quot;hi&quot;"),
        ("it's fine", "it&#39;s fine"),
        ("plain text", "plain text"),
        ("", ""),
    ])
    def test_escape(self, raw, expected):
        assert _html_escape(raw) == expected
