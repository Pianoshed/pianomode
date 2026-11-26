"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { disableTwoFactor, enableTwoFactor, newRecoveryCodes, setupTwoFactor } from "@/lib/account/api";
import { groupSecret, recoveryCodesText } from "@/lib/account/format";

function RecoveryCodes({ codes, account, onDone }: { codes: string[]; account: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  function download() {
    const blob = new Blob([recoveryCodesText(codes, account)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "keystudy-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="space-y-3">
      <Notice tone="info">
        Save these recovery codes now. They are shown only this once. Each works one time if you lose your phone.
      </Notice>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-sm" aria-label="Recovery codes">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonStyles()} onClick={download}>Download</button>
        <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={async () => { try { await navigator.clipboard.writeText(codes.join("\n")); setCopied(true); } catch { setCopied(false); } }}>
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" className={buttonStyles({ variant: "ghost" })} onClick={onDone}>I have saved them</button>
      </div>
    </div>
  );
}

export function TwoFactorForm({ enabled, setupNeeded, account }: { enabled: boolean; setupNeeded: boolean; account: string }) {
  const router = useRouter();
  const { pending, error, run } = useAction();
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<"idle" | "disable">("idle");
  const [copiedKey, setCopiedKey] = useState(false);

  async function start() {
    const r = await run(() => setupTwoFactor());
    if (r.ok) setSetup(r.data);
  }
  async function confirm(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => enableTwoFactor(code));
    if (r.ok) {
      setCodes(r.data.recovery_codes);
      setSetup(null);
      setCode("");
    }
  }
  async function turnOff(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => disableTwoFactor(password, code));
    if (r.ok) {
      setMode("idle");
      setPassword("");
      setCode("");
      router.refresh();
    }
  }
  async function regenerate(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => newRecoveryCodes(code));
    if (r.ok) {
      setCodes(r.data.recovery_codes);
      setCode("");
    }
  }

  return (
    <Card title="Two-factor sign-in">
      <div className="space-y-4">
        {setupNeeded && !enabled ? (
          <Notice tone="error">Your administrator role needs two-factor sign-in. Turn it on below to use admin tools.</Notice>
        ) : null}
        {error ? <Notice tone="error">{error}</Notice> : null}

        {codes ? (
          <RecoveryCodes codes={codes} account={account} onDone={() => { setCodes(null); router.refresh(); }} />
        ) : enabled ? (
          mode === "disable" ? (
            <form onSubmit={turnOff} className="space-y-3">
              <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              <Field label="Code from your app (or a recovery code)" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} />
              <div className="flex gap-2">
                <button type="submit" disabled={pending} className={buttonStyles()}>Turn off two-factor</button>
                <button type="button" onClick={() => setMode("idle")} className={buttonStyles({ variant: "ghost" })}>Cancel</button>
              </div>
            </form>
          ) : (
            <div className="space-y-3">
              <Notice tone="success">Two-factor sign-in is on. Signing in needs a code from your authenticator app.</Notice>
              <form onSubmit={regenerate} className="flex flex-wrap items-end gap-2">
                <div className="min-w-48 flex-1">
                  <Field label="Make new recovery codes" inputMode="numeric" autoComplete="one-time-code" placeholder="Code from your app" value={code} onChange={(e) => setCode(e.target.value)} hint="The old recovery codes stop working." />
                </div>
                <button type="submit" disabled={pending || !code} className={buttonStyles({ variant: "secondary" })}>New codes</button>
              </form>
              <button type="button" onClick={() => { setMode("disable"); setCode(""); }} className={buttonStyles({ variant: "ghost" })}>Turn off…</button>
            </div>
          )
        ) : setup ? (
          <form onSubmit={confirm} className="space-y-3">
            <p className="max-w-[60ch] text-sm">
              1. In an authenticator app (Google Authenticator, Authy, 1Password…) add an account and enter this key:
            </p>
            <p className="select-all break-all rounded-lg bg-surface-2 p-3 font-mono text-base" aria-label="Setup key">{groupSecret(setup.secret)}</p>
            <div className="flex flex-wrap gap-3 text-sm">
              <button type="button" className="underline underline-offset-4" onClick={async () => { try { await navigator.clipboard.writeText(setup.secret); setCopiedKey(true); } catch { setCopiedKey(false); } }}>
                {copiedKey ? "Key copied" : "Copy key"}
              </button>
              <a className="underline underline-offset-4" href={setup.uri}>Open in my authenticator app</a>
            </div>
            <p className="text-sm">2. Type the 6-digit code the app shows:</p>
            <Field label="Code" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} />
            <button type="submit" disabled={pending} className={buttonStyles()}>Turn on two-factor</button>
          </form>
        ) : (
          <div className="space-y-3">
            <p className="max-w-[60ch] text-sm text-muted">
              Adds a 6-digit code from your phone to signing in, so a stolen password alone cannot open your account.
            </p>
            <button type="button" disabled={pending} onClick={() => void start()} className={buttonStyles()}>
              {pending ? "Preparing…" : "Set up two-factor"}
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}
