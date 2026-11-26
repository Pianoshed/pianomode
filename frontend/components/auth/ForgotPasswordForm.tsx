"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { api } from "@/lib/api";

export function ForgotPasswordForm() {
  const { pending, error, run } = useAction();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => api("/api/v1/auth/password-reset/request", { method: "POST", body: { email } }));
    if (r.ok) setSent(true);
  }

  if (sent) {
    return <Notice tone="success">If that email has an account, a reset link is on its way. It expires in 1 hour.</Notice>;
  }
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Field label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <button type="submit" disabled={pending} className={`${buttonStyles()} w-full`}>
        {pending ? "Sending…" : "Send reset link"}
      </button>
      <Link href="/login" className="text-sm underline underline-offset-4">Back to sign in</Link>
    </form>
  );
}
