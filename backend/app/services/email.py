import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import AppError, ServiceUnavailableError

logger = logging.getLogger("app.email")


class EmailDeliveryError(AppError):
    status_code = 503
    code = "email_delivery_failed"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Development sender: logs the email, links included. Never use in production."""

    def send(self, message: EmailMessage) -> None:
        logger.warning("DEV EMAIL to=%s subject=%s\n%s", message.to, message.subject, message.body)


class ResendEmailSender:
    """Sends through Resend (https://resend.com/docs/api-reference/emails/send-email).

    `from_address` must be on a domain verified in Resend, or Resend will refuse the message.
    Raises EmailDeliveryError when Resend cannot be reached or refuses, so callers can decide
    whether to retry later.
    """

    def __init__(
        self, api_key: str, from_address: str, base_url: str = "https://api.resend.com"
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._from = from_address
        self._url = f"{base_url.rstrip('/')}/emails"

    def send(self, message: EmailMessage) -> None:
        try:
            res = httpx.post(
                self._url,
                headers=self._headers,
                json={
                    "from": self._from,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.body,
                },
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            logger.warning("Resend unreachable: %s", type(exc).__name__)
            raise EmailDeliveryError("Could not send the email. Try again shortly.") from exc
        if res.status_code >= 400:
            # The body says why (unverified domain, bad address). It holds no secrets.
            logger.error("Resend refused an email (%s): %s", res.status_code, res.text[:300])
            raise EmailDeliveryError("Could not send the email. Try again shortly.")


@dataclass
class InMemoryEmailSender:
    messages: list[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


_console = ConsoleEmailSender()


def build_sender() -> EmailSender:
    """Resend when a key is set; the console in development; an error in production without one."""
    settings = get_settings()
    if settings.resend_api_key:
        return ResendEmailSender(
            settings.resend_api_key, settings.email_from, settings.resend_base_url
        )
    if settings.is_production:
        raise ServiceUnavailableError(
            "Email delivery is not configured.", code="email_not_configured"
        )
    return _console


def get_email_sender() -> EmailSender:
    return build_sender()
