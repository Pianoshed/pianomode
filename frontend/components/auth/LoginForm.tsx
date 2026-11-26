"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { api } from "@/lib/api";

export function LoginForm() {
  const router = useRouter();
  const { pending, error, run, clearError } = useAction();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needsCode, setNeedsCode] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const r = await run(() =>
      api("/api/v1/auth/login", { method: "POST", body: { identifier, password, ...(needsCode ? { otp } : {}) } }),
    );
    if (r.ok) {
      router.replace("/dashboard");
      router.refresh();
    } else if (r.code === "two_factor_required") {
      // Password was right; ask for the authenticator code instead of showing an error.
      clearError();
      setNeedsCode(true);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error ? <Notice tone="error">{error}</Notice> : null}
      {needsCode ? (
        <>
          <Notice tone="info">Enter the 6-digit code from your authenticator app. Lost your phone? Use one of your recovery codes instead.</Notice>
          <Field label="Code" type="text" inputMode="numeric" autoComplete="one-time-code" autoCapitalize="none" spellCheck={false} required autoFocus value={otp} onChange={(e) => setOtp(e.target.value)} />
        </>
      ) : (
        <>
          <Field label="Email or login ID" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} required hint="Schools and studios: use the login ID your institution gave you." value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
          <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </>
      )}
      <button type="submit" disabled={pending} className={`${buttonStyles()} w-full`}>
        {pending ? "Signing in…" : needsCode ? "Verify and sign in" : "Sign in"}
      </button>
      {needsCode ? (
        <button type="button" onClick={() => { setNeedsCode(false); setOtp(""); clearError(); }} className={`${buttonStyles({ variant: "ghost" })} w-full`}>
          Back
        </button>
      ) : (
        <p className="flex flex-wrap justify-between gap-2 text-sm">
          <Link href="/forgot-password" className="underline underline-offset-4">Forgot password?</Link>
          <Link href="/register" className="underline underline-offset-4">Create an account</Link>
        </p>
      )}
    </form>
  );
}
