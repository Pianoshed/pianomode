"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { api } from "@/lib/api";

export function ResetPasswordForm() {
  const token = useSearchParams().get("token");
  const { pending, error, run } = useAction();
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);

  if (!token) {
    return <Notice tone="error">This link is missing its token. Request a new reset link.</Notice>;
  }
  if (done) {
    return (
      <div className="space-y-4">
        <Notice tone="success">Password changed. Sign in with your new password.</Notice>
        <Link href="/login" className={buttonStyles()}>Sign in</Link>
      </div>
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const r = await run(() =>
      api("/api/v1/auth/password-reset/confirm", { method: "POST", body: { token, new_password: password } }),
    );
    if (r.ok) setDone(true);
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Field label="New password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} hint="At least 10 characters." value={password} onChange={(e) => setPassword(e.target.value)} />
      <button type="submit" disabled={pending} className={`${buttonStyles()} w-full`}>
        {pending ? "Saving…" : "Set new password"}
      </button>
    </form>
  );
}
