from celery.schedules import crontab

from app.core.config import get_settings
from app.core.db import get_session
from app.services import expiry_service, maintenance_service, renewal_service
from app.services.email import build_sender
from app.services.paystack import HttpPaystackClient
from app.workers.celery_app import celery_app


@celery_app.task(name="billing.send_expiry_reminders")  # type: ignore[misc]
def send_expiry_reminders() -> dict[str, int]:
    session = next(get_session())
    try:
        result = expiry_service.send_expiry_reminders(session, build_sender(), get_settings())
    finally:
        session.close()
    return {"sent": result.sent, "failed": result.failed, "skipped": result.skipped}


@celery_app.task(name="billing.run_renewals")  # type: ignore[misc]
def run_renewals() -> dict[str, int]:
    settings = get_settings()
    if not settings.auto_renewal_enabled:
        return {"charged": 0, "failed": 0, "skipped": 0}
    client = HttpPaystackClient(settings.paystack_secret_key, settings.paystack_base_url)
    session = next(get_session())
    try:
        result = renewal_service.run_renewals(session, client, build_sender(), settings)
    finally:
        session.close()
    return {"charged": result.charged, "failed": result.failed, "skipped": result.skipped}


@celery_app.task(name="maintenance.purge_expired")  # type: ignore[misc]
def purge_expired() -> dict[str, int]:
    session = next(get_session())
    try:
        result = maintenance_service.purge_expired(session)
    finally:
        session.close()
    return {"sessions": result.sessions, "tokens": result.tokens}


# 07:00 UTC is 08:00 in Nigeria.
celery_app.conf.beat_schedule = {
    "expiry-reminders-daily": {
        "task": "billing.send_expiry_reminders",
        "schedule": crontab(hour=7, minute=0),
    },
    # Before the 07:00 reminder emails, so they match what happened to the renewal.
    "renewals-daily": {
        "task": "billing.run_renewals",
        "schedule": crontab(hour=6, minute=0),
    },
    "purge-expired-daily": {
        "task": "maintenance.purge_expired",
        "schedule": crontab(hour=3, minute=30),
    },
}
