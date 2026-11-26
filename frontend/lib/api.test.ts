import { afterEach, describe, expect, it, vi } from "vitest";
import { api, failureText } from "@/lib/api";

function stubFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("returns data on success", async () => {
    stubFetch(async () => new Response(JSON.stringify({ a: 1 }), { status: 200 }));
    expect(await api("/x")).toEqual({ ok: true, data: { a: 1 } });
  });

  it("treats 204 as success with no body", async () => {
    stubFetch(async () => new Response(null, { status: 204 }));
    expect(await api("/x", { method: "POST" })).toEqual({ ok: true, data: undefined });
  });

  it("maps the API error format", async () => {
    stubFetch(
      async () =>
        new Response(JSON.stringify({ error: { code: "invalid_credentials", message: "Nope." } }), {
          status: 401,
        }),
    );
    expect(await api("/x")).toEqual({
      ok: false,
      status: 401,
      code: "invalid_credentials",
      message: "Nope.",
    });
  });

  it("survives non-JSON error bodies and network failures", async () => {
    stubFetch(async () => new Response("<html>bad gateway</html>", { status: 502 }));
    const r = await api("/x");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("unknown_error");

    stubFetch(async () => {
      throw new TypeError("failed");
    });
    const n = await api("/x");
    expect(n.ok === false && n.code).toBe("network_error");
  });

  it("writes friendly text for rate limits and validation", () => {
    const base = { ok: false as const, status: 0, message: "raw" };
    expect(failureText({ ...base, code: "rate_limited" })).toMatch(/Too many/);
    expect(failureText({ ...base, code: "validation_error" })).toMatch(/Check/);
    expect(failureText({ ...base, code: "other" })).toBe("raw");
  });
});
