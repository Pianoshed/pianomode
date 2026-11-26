"use client";

import { useState } from "react";
import { failureText, type ApiResult } from "@/lib/api";

/** Tracks a pending request and the last error text for a form. */
export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run<T>(call: () => Promise<ApiResult<T>>): Promise<ApiResult<T>> {
    setPending(true);
    setError(null);
    const result = await call();
    setPending(false);
    if (!result.ok) setError(failureText(result));
    return result;
  }

  return { pending, error, run, clearError: () => setError(null) };
}
