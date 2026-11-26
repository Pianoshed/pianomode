"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { createSeats, getInstitution, resetSeatPassword, setSeatActive } from "@/lib/billing/api";
import { credentialsCsv, formatDate, parseNames } from "@/lib/billing/format";
import type { Credential, InstitutionOverview } from "@/lib/billing/types";

function downloadCsv(institution: string, rows: Credential[]) {
  const blob = new Blob([credentialsCsv(institution, rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "logins.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function InstitutionManager({ initial }: { initial: InstitutionOverview }) {
  const [data, setData] = useState(initial);
  const [names, setNames] = useState("");
  const [fresh, setFresh] = useState<Credential[] | null>(null);
  const [copied, setCopied] = useState(false);
  const { pending, error, run } = useAction();

  const free = Math.max(0, data.seats_allowed - data.seats_used);
  const parsed = parseNames(names);

  async function refresh() {
    const r = await getInstitution();
    if (r.ok) setData(r.data);
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => createSeats(parsed));
    if (r.ok) {
      setFresh(r.data.credentials);
      setNames("");
      setCopied(false);
      await refresh();
    }
  }

  async function onReset(s: { id: string; name: string }) {
    if (!window.confirm(`Make a new password for ${s.name}? Their old password stops working and they are signed out.`)) return;
    const r = await run(() => resetSeatPassword(s.id));
    if (r.ok) {
      setFresh(r.data.credentials);
      setCopied(false);
    }
  }

  async function onToggle(s: { id: string; name: string; active: boolean }) {
    if (s.active && !window.confirm(`Close the login for ${s.name}? They are signed out now and cannot sign in again. This frees a place for someone else.`)) return;
    const r = await run(() => setSeatActive(s.id, !s.active));
    if (r.ok) await refresh();
  }

  async function copyAll(rows: Credential[]) {
    const text = rows.map((c) => `${c.name}\t${c.login_id}\t${c.password}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="grid max-w-4xl gap-4">
      <Card title={data.name}>
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted">Logins in use</dt>
            <dd className="text-2xl font-bold">
              {data.seats_used} <span className="text-base font-medium text-muted">of {data.seats_allowed}</span>
            </dd>
          </div>
          <div>
            <dt className="text-muted">Plan runs until</dt>
            <dd className="font-semibold">{data.ends_at ? formatDate(data.ends_at) : "No plan"}</dd>
          </div>
          <div>
            <dt className="text-muted">Login ID prefix</dt>
            <dd className="font-mono font-semibold">{data.code}-</dd>
          </div>
        </dl>
        {!data.subscription_live ? (
          <div className="mt-4">
            <Notice tone="error">
              Your plan has ended, so none of your people can use the app and you cannot add logins.{" "}
              <Link href="/subscription" className="underline underline-offset-4">Renew your plan</Link>
            </Notice>
          </div>
        ) : null}
      </Card>

      {fresh ? (
        <Card title={fresh.length === 1 ? "New login" : `${fresh.length} new logins`}>
          <div className="space-y-3">
            <Notice tone="info">
              These passwords are shown only now and cannot be looked up later. Download or copy them before you leave
              this page. If one is lost, make a new password for that person.
            </Notice>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-muted">
                  <tr><th className="py-1 pr-4 font-medium">Name</th><th className="py-1 pr-4 font-medium">Login ID</th><th className="py-1 font-medium">Password</th></tr>
                </thead>
                <tbody className="font-mono">
                  {fresh.map((c) => (
                    <tr key={c.id} className="border-t border-line">
                      <td className="py-1.5 pr-4 font-sans">{c.name}</td>
                      <td className="py-1.5 pr-4">{c.login_id}</td>
                      <td className="py-1.5">{c.password}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" className={buttonStyles()} onClick={() => downloadCsv(data.name, fresh)}>
                Download as spreadsheet
              </button>
              <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => void copyAll(fresh)}>
                {copied ? "Copied" : "Copy"}
              </button>
              <button type="button" className={buttonStyles({ variant: "ghost" })} onClick={() => setFresh(null)}>
                I have saved them
              </button>
            </div>
            <p className="text-sm text-muted">
              People sign in at the normal sign-in page and type the <strong>Login ID</strong> where the email goes.
              A login works on one device at a time.
            </p>
          </div>
        </Card>
      ) : null}

      {data.subscription_live ? (
        <Card title="Add people">
          <form onSubmit={onCreate} className="space-y-3">
            {error ? <Notice tone="error">{error}</Notice> : null}
            <label htmlFor="names" className="text-sm font-medium">
              One name per line ({free} {free === 1 ? "place" : "places"} left)
            </label>
            <textarea
              id="names"
              rows={5}
              value={names}
              onChange={(e) => setNames(e.target.value)}
              disabled={free === 0}
              placeholder={"Ada Obi\nTunde Bello"}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-base text-fg placeholder:text-muted disabled:opacity-60"
            />
            {parsed.length > free && free > 0 ? (
              <p className="text-sm text-danger">That is {parsed.length} names but only {free} places are free.</p>
            ) : null}
            <button
              type="submit"
              disabled={pending || parsed.length === 0 || parsed.length > Math.min(free, 20)}
              className={buttonStyles()}
            >
              {pending ? "Creating…" : `Create ${parsed.length || ""} login${parsed.length === 1 ? "" : "s"}`.replace("  ", " ")}
            </button>
            {free === 0 ? (
              <p className="text-sm text-muted">All places are in use. Close a login below to free one.</p>
            ) : null}
          </form>
        </Card>
      ) : null}

      <Card title="Your people">
        {data.seats.length === 0 ? (
          <p className="text-sm text-muted">No logins yet. Add names above and each person gets their own.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-4 font-medium">Name</th>
                  <th className="py-1 pr-4 font-medium">Login ID</th>
                  <th className="py-1 pr-4 font-medium">Last sign-in</th>
                  <th className="py-1 font-medium"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {data.seats.map((s) => (
                  <tr key={s.id} className="border-t border-line align-middle">
                    <td className="py-2 pr-4">
                      {s.name}
                      {!s.active ? <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-xs text-muted">Closed</span> : null}
                    </td>
                    <td className="py-2 pr-4 font-mono">{s.login_id}</td>
                    <td className="py-2 pr-4 text-muted">{s.last_login_at ? formatDate(s.last_login_at) : "Never"}</td>
                    <td className="flex flex-wrap justify-end gap-2 py-2">
                      {s.active ? (
                        <button type="button" disabled={pending} className={buttonStyles({ variant: "secondary" })} onClick={() => void onReset(s)}>
                          New password
                        </button>
                      ) : null}
                      <button type="button" disabled={pending} className={buttonStyles({ variant: "ghost" })} onClick={() => void onToggle(s)}>
                        {s.active ? "Close login" : "Reopen"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
