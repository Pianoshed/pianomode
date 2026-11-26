"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { api } from "@/lib/api";

export function RegisterForm() {
  const { pending, error, run } = useAction();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const r = await run(() =>
      api("/api/v1/auth/register", {
        method: "POST",
        body: { email, password, display_name: displayName },
      }),
    );
    if (r.ok) setSentTo(email);
  }

  if (sentTo) {
    return (
      <div className="space-y-4">
        <Notice tone="success">
          We sent a message to {sentTo}. Open the link in it to finish creating your account.
        </Notice>
        <Link href="/login" className={buttonStyles({ variant: "secondary" })}>
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Field label="Your name" autoComplete="name" required maxLength={100} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      <Field label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} hint="At least 10 characters. A few words in a row works well." value={password} onChange={(e) => setPassword(e.target.value)} />
      <button type="submit" disabled={pending} className={`${buttonStyles()} w-full`}>
        {pending ? "Creating account…" : "Create account"}
      </button>
      <p className="text-sm text-muted">
        By creating an account you agree to the{" "}
        <Link href="/terms" className="underline underline-offset-4">Terms</Link> and have read the{" "}
        <Link href="/privacy" className="underline underline-offset-4">Privacy</Link> page.
      </p>
      <p className="text-sm">
        Already have an account?{" "}
        <Link href="/login" className="underline underline-offset-4">Sign in</Link>
      </p>
    </form>
  );
}
