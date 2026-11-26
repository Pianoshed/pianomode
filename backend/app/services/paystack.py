"""Paystack client: start a checkout, verify a transaction, check a webhook signature.

The client is a Protocol so tests (and local development without keys) can swap in a fake.
Amounts are always kobo. Docs: https://paystack.com/docs/api/transaction/
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError

logger = logging.getLogger("app.paystack")


class PaystackError(Exception):
    """Paystack could not be reached or refused the request."""


@dataclass(frozen=True)
class CheckoutSession:
    authorization_url: str
    access_code: str


@dataclass(frozen=True)
class CardAuthorization:
    """What Paystack lets us keep about a card that paid: a token, not the card number."""

    code: str
    reusable: bool
    channel: str  # "card", "bank_transfer", "ussd", ...
    brand: str = ""
    last4: str = ""
    exp_month: str = ""
    exp_year: str = ""


@dataclass(frozen=True)
class VerifiedTransaction:
    reference: str
    status: str  # Paystack: success, failed, abandoned, ongoing, pending, reversed, ...
    amount_kobo: int
    currency: str
    gateway_response: str
    authorization: CardAuthorization | None = None


class PaystackClient(Protocol):
    def initialize(
        self,
        *,
        email: str,
        amount_kobo: int,
        reference: str,
        callback_url: str,
        metadata: dict[str, Any],
    ) -> CheckoutSession: ...

    def verify(self, reference: str) -> VerifiedTransaction: ...

    def charge_authorization(
        self,
        *,
        email: str,
        amount_kobo: int,
        reference: str,
        authorization_code: str,
        metadata: dict[str, Any],
    ) -> None:
        """Charge a saved card. The outcome is read with `verify(reference)` afterwards."""
        ...


class HttpPaystackClient:
    def __init__(self, secret_key: str, base_url: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {secret_key}"}
        self._timeout = timeout

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            res = httpx.request(
                method,
                f"{self._base}{path}",
                headers=self._headers,
                timeout=self._timeout,
                **kwargs,
            )
            body = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Paystack call failed: %s", type(exc).__name__)
            raise PaystackError("Could not reach Paystack.") from exc
        if res.status_code >= 400 or not body.get("status"):
            logger.warning("Paystack refused %s: %s", path, body.get("message"))
            raise PaystackError(str(body.get("message", "Paystack refused the request.")))
        data = body.get("data")
        if not isinstance(data, dict):
            raise PaystackError("Unexpected reply from Paystack.")
        return data

    def initialize(
        self,
        *,
        email: str,
        amount_kobo: int,
        reference: str,
        callback_url: str,
        metadata: dict[str, Any],
    ) -> CheckoutSession:
        data = self._call(
            "POST",
            "/transaction/initialize",
            json={
                "email": email,
                "amount": amount_kobo,
                "currency": "NGN",
                "reference": reference,
                "callback_url": callback_url,
                "metadata": metadata,
            },
        )
        return CheckoutSession(str(data["authorization_url"]), str(data["access_code"]))

    def charge_authorization(
        self,
        *,
        email: str,
        amount_kobo: int,
        reference: str,
        authorization_code: str,
        metadata: dict[str, Any],
    ) -> None:
        self._call(
            "POST",
            "/transaction/charge_authorization",
            json={
                "email": email,
                "amount": amount_kobo,
                "currency": "NGN",
                "reference": reference,
                "authorization_code": authorization_code,
                "metadata": metadata,
            },
        )

    def verify(self, reference: str) -> VerifiedTransaction:
        data = self._call("GET", f"/transaction/verify/{reference}")
        return VerifiedTransaction(
            reference=str(data.get("reference", "")),
            status=str(data.get("status", "")),
            amount_kobo=int(data.get("amount", 0)),
            currency=str(data.get("currency", "")),
            gateway_response=str(data.get("gateway_response", ""))[:255],
            authorization=_authorization(data.get("authorization")),
        )


def _authorization(raw: Any) -> CardAuthorization | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("authorization_code"), str):
        return None
    return CardAuthorization(
        code=raw["authorization_code"],
        reusable=raw.get("reusable") is True,
        channel=str(raw.get("channel", "")),
        brand=str(raw.get("card_type", "")).strip()[:24],
        last4=str(raw.get("last4", ""))[:4],
        exp_month=str(raw.get("exp_month", ""))[:2],
        exp_year=str(raw.get("exp_year", ""))[:4],
    )


def get_paystack_client() -> PaystackClient:
    settings = get_settings()
    if not settings.paystack_secret_key:
        raise ServiceUnavailableError(
            "Online payment is not set up yet.", code="billing_not_configured"
        )
    return HttpPaystackClient(settings.paystack_secret_key, settings.paystack_base_url)


def signature_is_valid(raw_body: bytes, header: str | None, secret_key: str) -> bool:
    """Paystack signs the raw request body with HMAC-SHA512 using your secret key."""
    if not header or not secret_key:
        return False
    expected = hmac.new(secret_key.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, header.strip().lower())
