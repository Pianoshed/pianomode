"use client";

import { useCallback, useEffect, useState } from "react";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { changeRole, getAudit, getPerson, listPeople, personAction, refundPayment } from "@/lib/admin/api";
import { KIND_LABEL, describeAction } from "@/lib/admin/format";
import type { AuditAction, PersonDetail, PersonRow } from "@/lib/admin/types";
import { describeEntitlement, formatDate, formatNaira } from "@/lib/billing/format";
import { formatBytes } from "@/lib/library/format";

const PAGE = 25;

export function PeopleAdmin() {
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<PersonRow[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<PersonDetail | null>(null);
  const [audit, setAudit] = useState<AuditAction[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const list = useAction();
  const act = useAction();

  const load = useCallback(async () => {
    const r = await list.run(() => listPeople(q, role, offset));
    if (r.ok) {
      setRows(r.data.users);
      setTotal(r.data.total);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, role, offset]);

  useEffect(() => {
    const t = setTimeout(() => void load(), 250); // wait for the typing to pause
    return () => clearTimeout(t);
  }, [load]);

  async function open(id: string, keepNote = false) {
    if (!keepNote) setNote(null);
    const r = await act.run(() => getPerson(id));
    if (r.ok) setSelected(r.data);
  }

  async function doAction(label: string, call: () => Promise<{ ok: boolean }>, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setNote(null);
    const r = await act.run(call as never);
    if (r.ok && selected) {
      setNote(`${label}.`);
      await open(selected.id, true); // refresh the panel, but keep the confirmation visible
      await load();
      if (audit) void showAudit();
    }
  }

  async function showAudit() {
    const r = await act.run(() => getAudit());
    if (r.ok) setAudit(r.data.actions);
  }

  const p = selected;
  const staff = (r: string) => p?.roles.includes(r) ?? false;
  const seatOrSelf = p?.kind === "seat";

  return (
    <div className="grid max-w-5xl gap-4">
      <Card title="Find people">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-56 flex-1 text-sm font-medium">
            Name, email or login ID
            <input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} className="mt-1 block min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-base text-fg" />
          </label>
          <label className="text-sm font-medium">
            Role
            <select value={role} onChange={(e) => { setRole(e.target.value); setOffset(0); }} className="mt-1 block min-h-11 rounded-lg border border-line bg-surface px-3 text-base text-fg">
              <option value="">Everyone</option>
              <option value="admin">Admins</option>
              <option value="educator">Educators</option>
              <option value="learner">Learners</option>
            </select>
          </label>
        </div>
        {list.error ? <div className="mt-3"><Notice tone="error">{list.error}</Notice></div> : null}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr><th className="py-1 pr-4 font-medium">Name</th><th className="py-1 pr-4 font-medium">Sign-in</th><th className="py-1 pr-4 font-medium">Type</th><th className="py-1 pr-4 font-medium">Status</th><th className="py-1 font-medium"><span className="sr-only">Open</span></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={`border-t border-line ${selected?.id === r.id ? "bg-accent-soft" : ""}`}>
                  <td className="py-2 pr-4">{r.name}{r.roles.filter((x) => x !== "learner").map((x) => <span key={x} className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-xs">{x}</span>)}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{r.email ?? r.login_id}</td>
                  <td className="py-2 pr-4">{KIND_LABEL[r.kind]}</td>
                  <td className="py-2 pr-4">{r.is_active ? "Active" : "Closed"}{r.two_factor_enabled ? " · 2FA" : ""}</td>
                  <td className="py-2"><button type="button" onClick={() => void open(r.id)} className={buttonStyles({ variant: "secondary" })}>View</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && !list.error ? <p className="py-3 text-sm text-muted">Nobody matches.</p> : null}
        </div>
        <div className="mt-3 flex items-center justify-between text-sm text-muted">
          <span>{total === 0 ? "0 people" : `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}`}</span>
          <span className="flex gap-2">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className={buttonStyles({ variant: "ghost" })}>Previous</button>
            <button type="button" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} className={buttonStyles({ variant: "ghost" })}>Next</button>
          </span>
        </div>
      </Card>

      {act.error ? <Notice tone="error">{act.error}</Notice> : null}
      {note ? <Notice tone="success">{note}</Notice> : null}

      {p ? (
        <Card title={p.name}>
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="text-muted">Sign-in</dt><dd className="font-semibold break-all">{p.email ?? p.login_id}</dd></div>
            <div><dt className="text-muted">Plan</dt><dd className="font-semibold">{describeEntitlement(p.entitlement).headline}</dd></div>
            <div><dt className="text-muted">Institution</dt><dd className="font-semibold">{p.institution_name ?? "None"}</dd></div>
            <div><dt className="text-muted">Joined</dt><dd>{formatDate(p.created_at)}</dd></div>
            <div><dt className="text-muted">Saved work</dt><dd>{p.library_items} items · {formatBytes(p.library_bytes)}</dd></div>
            <div><dt className="text-muted">Signed in on</dt><dd>{p.active_sessions} device{p.active_sessions === 1 ? "" : "s"}</dd></div>
          </dl>

          <div className="mt-4 flex flex-wrap gap-2">
            {p.is_active ? (
              <button type="button" disabled={act.pending || seatOrSelf} className={buttonStyles({ variant: "secondary" })}
                onClick={() => void doAction("Account closed", () => personAction(p.id, "close"), `Close ${p.name}'s account? They are signed out at once.`)}>Close account</button>
            ) : (
              <button type="button" disabled={act.pending || seatOrSelf} className={buttonStyles()} onClick={() => void doAction("Account reopened", () => personAction(p.id, "reopen"))}>Reopen account</button>
            )}
            <button type="button" disabled={act.pending} className={buttonStyles({ variant: "secondary" })} onClick={() => void doAction("Signed out everywhere", () => personAction(p.id, "sign-out"))}>Sign out everywhere</button>
            {!seatOrSelf ? (
              <>
                <button type="button" disabled={act.pending} className={buttonStyles({ variant: "ghost" })}
                  onClick={() => void doAction(staff("educator") ? "Educator role removed" : "Educator role given", () => changeRole(p.id, "educator", !staff("educator")))}>
                  {staff("educator") ? "Remove educator" : "Make educator"}
                </button>
                <button type="button" disabled={act.pending} className={buttonStyles({ variant: "ghost" })}
                  onClick={() => void doAction(staff("admin") ? "Admin role removed" : "Admin role given", () => changeRole(p.id, "admin", !staff("admin")),
                    staff("admin") ? `Remove admin rights from ${p.name}?` : `Make ${p.name} an administrator? They will be able to see everyone and record payments.`)}>
                  {staff("admin") ? "Remove admin" : "Make admin"}
                </button>
              </>
            ) : null}
            {p.two_factor_enabled && !staff("admin") ? (
              <button type="button" disabled={act.pending} className={buttonStyles({ variant: "ghost" })}
                onClick={() => void doAction("Two-factor reset", () => personAction(p.id, "reset-two-factor"), "Turn off two-factor for this person (they lost their phone)? Check it is really them first.")}>Reset two-factor</button>
            ) : null}
          </div>

          <h3 className="mb-2 mt-6 text-sm font-semibold">Payments</h3>
          {p.payments.length === 0 ? <p className="text-sm text-muted">No payments.</p> : (
            <ul className="divide-y divide-line text-sm">
              {p.payments.map((x) => (
                <li key={x.reference} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>{x.kind === "upgrade" ? "Upgrade" : `${x.months} month${x.months === 1 ? "" : "s"}`} · {x.plan_code} · {formatNaira(x.amount_kobo)} · {x.status === "success" ? "Paid" : x.status === "refunded" ? "Refunded" : x.status} · {formatDate(x.paid_at ?? x.created_at)}</span>
                  {x.status === "success" ? (
                    <button type="button" disabled={act.pending} className={buttonStyles({ variant: "ghost" })} onClick={() => {
                      const reason = window.prompt("Why is this being refunded? (kept in the audit log)");
                      if (reason && reason.trim().length >= 3) void doAction("Access taken back", () => refundPayment(x.reference, reason.trim()));
                    }}>Take back access</button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-muted">Taking back access does not return the money. Refund the money in the Paystack dashboard; a full refund there takes the access back by itself.</p>
        </Card>
      ) : null}

      <Card title="Audit log" action={<button type="button" onClick={() => void showAudit()} className={buttonStyles({ variant: "secondary" })}>{audit ? "Refresh" : "Show"}</button>}>
        {audit === null ? <p className="text-sm text-muted">Everything an administrator does to access, roles or money is written here and cannot be edited.</p> : audit.length === 0 ? <p className="text-sm text-muted">Nothing recorded yet.</p> : (
          <ul className="divide-y divide-line text-sm">
            {audit.map((a) => (
              <li key={a.id} className="py-2">
                <p>{describeAction(a)}{a.target_label ? <> — <span className="font-mono text-xs">{a.target_label}</span></> : null}</p>
                <p className="text-xs text-muted">{a.actor_email} · {new Date(a.created_at).toLocaleString("en-GB")}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
