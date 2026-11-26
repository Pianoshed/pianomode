"""Charge saved cards for plans ending within a day. Safe to repeat: one attempt per plan per day.

cd backend && python -m scripts.run_renewals

Normally Celery beat does this at 06:00 UTC (app/workers/tasks.py). Needs
PIANO_AUTO_RENEWAL_ENABLED=true, otherwise it does nothing.
"""

from app.core.config import get_settings
from app.core.db import get_session
from app.services import renewal_service
from app.services.email import build_sender
from app.services.paystack import get_paystack_client


def main() -> None:
    settings = get_settings()
    session = next(get_session())
    try:
        r = renewal_service.run_renewals(session, get_paystack_client(), build_sender(), settings)
    finally:
        session.close()
    print(f"charged={r.charged} failed={r.failed} skipped={r.skipped}")


if __name__ == "__main__":
    main()
