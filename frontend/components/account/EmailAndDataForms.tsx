"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { EXPORT_URL, changeEmail, deleteAccount } from "@/lib/account/api";

export function ChangeEmailForm({ current }: { current: string }) {
  const { pending, error, run } = useAction();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSent(null);
    const r = await run(() => changeEmail(email, password));
    if (r.ok) {
      setSent(r.data.message);
      setPassword("");
    }
  }

  return (
    <Card title="Change email">
      <form onSubmit={onSubmit} className="space-y-4">
        <p className="max-w-[60ch] text-sm text-muted">
          Your email is {current}. We send a link to the new address; the email changes when you open it, and you
          will sign in again with the new address.
        </p>
        {error ? <Notice tone="error">{error}</Notice> : null}
        {sent ? <Notice tone="success">{sent}</Notice> : null}
        <Field label="New email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label="Your password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <button type="submit" disabled={pending} className={buttonStyles()}>{pending ? "Sending…" : "Send confirmation link"}</button>
      </form>
    </Card>
  );
}

export function DataCard() {
  return (
    <Card title="Your data">
      <p className="mb-3 max-w-[60ch] text-sm text-muted">
        Download everything we hold about you (profile, payments, saved work, practice results and sign-ins) as one
        file. Saved MIDI files are not inside it; download those from My Library.
      </p>
      <a href={EXPORT_URL} download className={buttonStyles({ variant: "secondary" })}>Download my data</a>
    </Card>
  );
}

export function DeleteAccountForm({ needsCode }: { needsCode: boolean }) {
  const router = useRouter();
  const { pending, error, run } = useAction();
  const [password, setPassword] = useState("");
  const [word, setWord] = useState("");
  const [otp, setOtp] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!window.confirm("Delete your account for good? Your saved work and progress are erased and cannot be recovered.")) return;
    const r = await run(() => deleteAccount(password, word.trim(), needsCode ? otp : undefined));
    if (r.ok) {
      router.replace("/");
      router.refresh();
    }
  }

  return (
    <Card title="Delete account">
      <form onSubmit={onSubmit} className="space-y-4">
        <p className="max-w-[60ch] text-sm text-muted">
          This erases your name, email, saved library, practice results and sign-ins for good. We keep only the payment
          records the law requires, without your name or email. This is different from closing your account, which
          keeps your data. Download your data first if you want a copy.
        </p>
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        {needsCode ? <Field label="Two-factor code" inputMode="numeric" autoComplete="one-time-code" required value={otp} onChange={(e) => setOtp(e.target.value)} /> : null}
        <Field label="Type DELETE to confirm" required autoCapitalize="characters" spellCheck={false} value={word} onChange={(e) => setWord(e.target.value)} />
        <button type="submit" disabled={pending || word.trim() !== "DELETE"} className="inline-flex min-h-11 items-center justify-center rounded-lg bg-danger px-4 text-sm font-semibold text-bg disabled:opacity-50">
          {pending ? "Deleting…" : "Delete my account"}
        </button>
      </form>
    </Card>
  );
}
