import { NextResponse, type NextRequest } from "next/server";

/**
 * Content-Security-Policy with a fresh nonce per request (docs/adr/0017-strict-csp.md).
 *
 * Two policies exist:
 *  - strict: scripts run only if they carry this request's nonce (plus what those scripts load).
 *    An injected <script> or inline handler is refused. Styles still allow 'unsafe-inline',
 *    because React's style="" attributes cannot carry a nonce; a style cannot run code.
 *  - compat: the older policy that allows inline scripts.
 *
 * Rollout: compat is the default, so nothing changes until you switch. Try strict on a test copy:
 * set CSP_ENFORCE_STRICT=true on the web service, restart it, and run `e2e/security.e2e.mjs` (it
 * fails on any policy violation in a real browser) and click through the app. Then set it in
 * production. (A Report-Only trial is not possible: Next.js only attaches nonces to its own
 * scripts when the nonce is in the enforced header.)
 */
function policy(nonce: string, strict: boolean): string {
  const script = strict
    ? `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`
    : "script-src 'self' 'unsafe-inline'";
  return [
    "default-src 'self'",
    script,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "media-src 'self' blob: data:",
    "connect-src 'self' blob:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ].join("; ");
}

export function middleware(request: NextRequest) {
  // Development tooling needs eval, so no policy there.
  if (process.env.NODE_ENV !== "production") return NextResponse.next();

  const nonce = btoa(crypto.randomUUID());
  const enforceStrict = process.env.CSP_ENFORCE_STRICT === "true";
  const csp = policy(nonce, enforceStrict);

  // Next.js reads the nonce from the request's policy and puts it on its own scripts.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  // Pages only: not the API, static files, images or the icon.
  matcher: [{ source: "/((?!api/|_next/static|_next/image|favicon.ico).*)" }],
};
