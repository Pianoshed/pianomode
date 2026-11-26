"""Send plan-ending reminder emails now. Safe to repeat: nothing is sent twice.

cd backend && python -m scripts.send_expiry_reminders

Normally Celery beat does this every morning (see app/workers/tasks.py). Use this from cron if you
run without Celery, or to run it by hand.
"""

from app.core.config import get_settings
from app.core.db import get_session
from app.services import expiry_service
from app.services.email import build_sender


def main() -> None:
    session = next(get_session())
    try:
        result = expiry_service.send_expiry_reminders(session, build_sender(), get_settings())
    finally:
        session.close()
    print(f"sent={result.sent} failed={result.failed} skipped={result.skipped}")


if __name__ == "__main__":
    main()
