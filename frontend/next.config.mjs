// The browser talks to /api/* on the web origin. In development Next forwards it to the API. In
// production the reverse proxy (Caddy, see Caddyfile) sends /api/* straight to the API instead, so
// this rewrite is only a fallback. It is read at build time, so set API_INTERNAL_URL when building.
const api = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

// The Content-Security-Policy (with a per-request nonce) is set in middleware.ts.

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // MIDI keyboards need the midi feature; nothing here uses the camera, microphone or location.
  { key: "Permissions-Policy", value: "midi=(self), camera=(), microphone=(), geolocation=(), payment=()" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // `standalone` makes a small self-contained server for the production Docker image.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
