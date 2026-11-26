from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIANO_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://piano:piano@localhost:5432/piano"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me"
    cors_origins: list[str] = ["http://localhost:3000"]
    public_web_url: str = "http://localhost:3000"
    storage_dir: str = "./var/storage"

    # My Library limits (per person)
    library_max_items: int = 200
    library_max_file_bytes: int = 5 * 1024 * 1024  # one MIDI file
    library_max_total_bytes: int = 100 * 1024 * 1024  # all their saved files together
    library_max_data_bytes: int = 200 * 1024  # the saved settings of one item

    session_cookie_name: str = "piano_session"
    session_ttl_days: int = 14
    session_idle_days: int = 7
    secure_cookies: bool | None = None  # None = secure in production only
    # How many reverse proxies sit between the internet and the API (0 = none, 1 = Caddy).
    trusted_proxies: int = 0
    rate_limit_backend: Literal["memory", "redis"] = "memory"

    # Administrators must use two-factor sign-in before they can open admin tools. Default: on in
    # production, off in development and tests. Set explicitly to override either way.
    admin_require_two_factor: bool | None = None

    # Error reporting (Sentry). Empty = off. No cookies, headers or user details are sent.
    sentry_dsn: str = ""

    # Email (Resend). With no key, development logs emails to the console instead.
    resend_api_key: str = ""
    resend_base_url: str = "https://api.resend.com"
    # Must be on a domain verified in Resend, e.g. "Piano Platform <hello@yourdomain.com>"
    email_from: str = "Piano Platform <onboarding@resend.dev>"

    # Password hashing is deliberately heavy (about 19 MB of memory each). When many people sign in
    # at once, running them all together only multiplies memory use (found by scripts/loadtest.py:
    # 50 at once peaked near 1 GB), so each server process hashes this many at a time and the rest
    # wait their turn. Roughly: the number of CPU cores per process.
    max_concurrent_hashes: int = 4

    # Billing (Paystack). Prices live in app/services/plans.py; amounts are in kobo.
    paystack_secret_key: str = ""
    paystack_base_url: str = "https://api.paystack.co"
    trial_days: int = 7  # free trial for individual accounts; 0 turns the trial off
    billing_period_days: int = 30  # one paid "month"
    # Refunds recorded by an administrator are refused after this many days from the payment unless
    # the administrator confirms an override (kept in the audit log). Matches the Refunds page
    # ("within 14 days"). 0 = no limit. A refund Paystack has already made is always recorded.
    refund_window_days: int = 14
    # Automatic card renewal (opt-in per person). Off until you have tried it with Paystack test
    # keys: see docs/adr/0016-automatic-renewal.md. Off = the checkbox is hidden and nothing is
    # charged by itself.
    auto_renewal_enabled: bool = False

    @property
    def admins_need_two_factor(self) -> bool:
        return (
            self.is_production
            if self.admin_require_two_factor is None
            else self.admin_require_two_factor
        )

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production if self.secure_cookies is None else self.secure_cookies


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        if settings.secret_key == "change-me":
            raise RuntimeError("PIANO_SECRET_KEY must be set in production")
        if len(settings.secret_key) < 32:
            raise RuntimeError("PIANO_SECRET_KEY must be at least 32 characters in production")
        if settings.rate_limit_backend != "redis":
            raise RuntimeError("PIANO_RATE_LIMIT_BACKEND must be 'redis' in production")
        if not settings.paystack_secret_key:
            raise RuntimeError("PIANO_PAYSTACK_SECRET_KEY must be set in production")
        if not settings.resend_api_key:
            raise RuntimeError("PIANO_RESEND_API_KEY must be set in production")
        if not settings.public_web_url.startswith("https://"):
            raise RuntimeError("PIANO_PUBLIC_WEB_URL must be an https:// address in production")
        if urlsplit(settings.redis_url).password is None:
            raise RuntimeError(
                "PIANO_REDIS_URL must include a password in production "
                "(redis://:PASSWORD@redis:6379/0)"
            )
        if settings.secure_cookies is False:
            raise RuntimeError("PIANO_SECURE_COOKIES must not be false in production")
        if settings.trusted_proxies < 1:
            raise RuntimeError(
                "PIANO_TRUSTED_PROXIES must be at least 1 in production (the number of reverse "
                "proxies in front of the API). Without it every user shares one rate-limit bucket."
            )
    return settings
