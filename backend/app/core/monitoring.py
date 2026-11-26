"""Optional error reporting to Sentry. Off unless PIANO_SENTRY_DSN is set."""

import logging

import sentry_sdk

from app.core.config import Settings

logger = logging.getLogger("app.monitoring")


def init_monitoring(settings: Settings) -> bool:
    """Start Sentry when a DSN is configured. Returns whether it was started.

    `send_default_pii=False` keeps cookies, auth headers and IP addresses out of reports, and no
    performance tracing is collected, so only error details (stack traces) leave the server.
    """
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
    logger.info("Error reporting is on")
    return True
