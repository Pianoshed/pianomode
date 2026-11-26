import { cookies, headers } from "next/headers";

/** Where server-rendered pages reach the API (inside the Docker network in production). */
export const apiBase = () => process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/**
 * Headers for a server-side call to the API on behalf of the person viewing the page: their
 * session cookie, and their real address. The address matters because the API counts rate limits
 * per person; without it every page load would look like it came from this web server.
 * `x-forwarded-for` is set by the reverse proxy (Caddy) in front of the web app, never by the browser.
 */
export async function apiHeaders(): Promise<Record<string, string>> {
  const forwarded = (await headers()).get("x-forwarded-for");
  return { cookie: (await cookies()).toString(), ...(forwarded ? { "x-forwarded-for": forwarded } : {}) };
}
