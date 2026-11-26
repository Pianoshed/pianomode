"""Who is really calling? The client address, when a reverse proxy sits in front of the API.

Behind Caddy (or any proxy) the connection comes from the proxy, so `request.client.host` is the
same for everybody and per-IP limits would punish all users together. Proxies add the real address
to the end of `X-Forwarded-For`. We trust exactly `trusted_proxies` entries from the right, because
anything further left can be written by the caller. With 0 (the default, for development and
direct access) the header is ignored, so it cannot be spoofed.
"""

import ipaddress

from fastapi import Request


def client_ip(request: Request, trusted_proxies: int) -> str:
    direct = request.client.host if request.client else "unknown"
    if trusted_proxies <= 0:
        return direct
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) < trusted_proxies:
        return direct  # header missing or shorter than our proxy chain: do not guess
    candidate = parts[-trusted_proxies]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return direct
