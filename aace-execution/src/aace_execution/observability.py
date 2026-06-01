"""Optional Sentry initialization.

Both the API process (``api.main``) and the worker process (``worker``)
call ``init_sentry()`` at startup. If ``SENTRY_DSN`` is unset, this is
a no-op — Sentry is opt-in via environment.

Failures to initialize (missing SDK, malformed DSN) are logged and
swallowed so observability never blocks the service from booting.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_sentry(*, service_name: str) -> None:
    """Initialize the Sentry SDK if ``SENTRY_DSN`` is set.

    Args:
        service_name: arbitrary tag, e.g. ``"aace-worker"`` or
            ``"aace-api"`` — shows up in the Sentry UI so you can
            filter events by component.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry_sdk not installed; SENTRY_DSN ignored")
        return
    try:
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(
                os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")
            ),
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            release=os.environ.get("SENTRY_RELEASE"),
            send_default_pii=False,
        )
        sentry_sdk.set_tag("service", service_name)
        logger.info("sentry_initialized", extra={"service": service_name})
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sentry_init_failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
