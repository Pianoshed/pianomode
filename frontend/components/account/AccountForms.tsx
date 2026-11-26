"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { api } from "@/lib/api";

export function ProfileForm({
  initialName,
  email,
  identifierLabel = "Email",
  hint = "To change it, use Change email below.",
}: {
  initialName: string;
  email: string;
  identifierLabel?: string;
  hint?: string;
}) {
  const router = useRouter();
  const { pending, error, run } = useAction();
  const [name, setName] = useState(initialName);
  const [saved, setSaved] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    const r = await run(() => api("/api/v1/auth/me", { method: "PATCH", body: { display_name: name } }));
    if (r.ok) {
      setSaved(true);
      router.refresh();
    }
  }

  return (
    <Card title="Profile">
      <form onSubmit={onSubmit} className="space-y-4">
        {error ? <Notice tone="error">{error}</Notice> : null}
        {saved ? <Notice tone="success">Profile saved.</Notice> : null}
        <Field label="Your name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <Field label={identifierLabel} value={email} readOnly hint={hint} />
        <button type="submit" disabled={pending} className={buttonStyles()}>
          {pending ? "Saving…" : "Save profile"}
        </button>
      </form>
    </Card>
  );
}

export function ChangePasswordForm() {
  const { pending, error, run } = useAction();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setDone(false);
    const r = await run(() =>
      api("/api/v1/auth/me/change-password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      }),
    );
    if (r.ok) {
      setDone(true);
      setCurrent("");
      setNext("");
    }
  }

  return (
    <Card title="Change password">
      <form onSubmit={onSubmit} className="space-y-4">
        {error ? <Notice tone="error">{error}</Notice> : null}
        {done ? <Notice tone="success">Password changed. Other devices were signed out.</Notice> : null}
        <Field label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        <Field label="New password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} hint="At least 10 characters." value={next} onChange={(e) => setNext(e.target.value)} />
        <button type="submit" disabled={pending} className={buttonStyles()}>
          {pending ? "Saving…" : "Change password"}
        </button>
      </form>
    </Card>
  );
}

export function DeactivateForm() {
  const router = useRouter();
  const { pending, error, run } = useAction();
  const [password, setPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => api("/api/v1/auth/me/deactivate", { method: "POST", body: { password } }));
    if (r.ok) {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <Card title="Close account">
      <form onSubmit={onSubmit} className="space-y-4">
        <p className="max-w-[60ch] text-sm text-muted">
          Closing your account signs you out everywhere and stops you from signing in, but keeps your data.
          Contact support to have it reopened. To erase your data instead, use Delete account.
        </p>
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="h-5 w-5 accent-[rgb(var(--c-danger))]" />
          I understand my account will be closed.
        </label>
        <button type="submit" disabled={pending || !confirmed} className="inline-flex min-h-11 items-center justify-center rounded-lg bg-danger px-4 text-sm font-semibold text-bg disabled:opacity-50">
          {pending ? "Closing…" : "Close my account"}
        </button>
      </form>
    </Card>
  );
}
