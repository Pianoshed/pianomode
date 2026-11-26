export type ApiFailure = { ok: false; status: number; code: string; message: string };
export type ApiResult<T> = { ok: true; data: T } | ApiFailure;

type Options = { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown };

/** Browser-side JSON call to the API. Never throws; failures come back as `{ ok: false }`. */
export async function api<T>(path: string, options: Options = {}): Promise<ApiResult<T>> {
  const { method = "GET", body } = options;
  try {
    const res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
    if (res.status === 204) return { ok: true, data: undefined as T };
    const json: unknown = await res.json().catch(() => null);
    if (res.ok) return { ok: true, data: json as T };
    const err = (json as { error?: { code?: string; message?: string } } | null)?.error;
    return {
      ok: false,
      status: res.status,
      code: err?.code ?? "unknown_error",
      message: err?.message ?? "Something went wrong. Try again.",
    };
  } catch {
    return {
      ok: false,
      status: 0,
      code: "network_error",
      message: "Could not reach the server. Check your connection and try again.",
    };
  }
}

/** Text safe to show a person for a failed call. */
export function failureText(f: ApiFailure): string {
  if (f.code === "validation_error") return "Check the highlighted details and try again.";
  if (f.code === "subscription_required") return "Your access has ended. Open Subscription to carry on.";
  if (f.code === "rate_limited") return "Too many attempts. Wait a few minutes and try again.";
  return f.message;
}
