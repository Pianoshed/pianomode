"use client";

import { useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { adminGrant, adminLookup, adminPayments, adminSendReminders } from "@/lib/billing/api";
import { refundCheck, refundPayment, refundWarning } from "@/lib/admin/api";
import { describeEntitlement, formatDate, formatNaira, parseNairaToKobo } from "@/lib/billing/format";
import type { AdminLookup, AdminPayment, PlansResponse } from "@/lib/billing/types";

export function BillingAdmin({ plans, initialPayments }: { plans: PlansResponse; initialPayments: AdminPayment[] }) {
  const [email, setEmail] = useState("");
  const [found, setFound] = useState<AdminLookup | null>(null);
  const [planCode, setPlanCode] = useState(plans.plans[0]?.code ?? "individual");
  const [months, setMonths] = useState(1);
  const [institutionName, setInstitutionName] = useState("");
  const [payments, setPayments] = useState(initialPayments);
  const [done, setDone] = useState<string | null>(null);
  const [reminders, setReminders] = useState<string | null>(null);
  const find = useAction();
  const grant = useAction();
  const remind = useAction();

  const plan = plans.plans.find((p) => p.code === planCode);
  const needsName = plan?.kind === "institution" && !found?.institution;

  async function lookup(address = email) {
    const r = await find.run(() => adminLookup(address.trim()));
    if (r.ok) setFound(r.data);
    return r.ok ? r.data : null;
  }

  async function onFind(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    await lookup();
  }

  async function onGrant(e: FormEvent) {
    e.preventDefault();
    if (!plan || !found?.found) return;
    const total = formatNaira(plan.monthly_kobo * months);
    const who = found.user?.email ?? email;
    if (!window.confirm(`Record ${total} (${plan.name}, ${months} month${months === 1 ? "" : "s"}) as received from ${who}? Their access starts now.`)) return;
    const r = await grant.run(() =>
      adminGrant({ email: who, plan: plan.code, months, ...(needsName ? { institution_name: institutionName } : {}) }),
    );
    if (!r.ok) return;
    setDone(`Recorded. ${who} now has ${plan.name} access.`);
    await lookup(who);
    const list = await adminPayments();
    if (list.ok) setPayments(list.data.payments);
  }

  async function onRefund(reference: string, part = false) {
    // Late, or from someone refunded before: ask for a clear yes before going on.
    let override = false;
    const check = await refundCheck(reference);
    if (check.ok) {
      const warning = refundWarning(check.data);
      if (warning) {
        if (!window.confirm(warning)) return;
        override = true;
      }
    }
    let amountKobo: number | undefined;
    if (part) {
      const text = window.prompt("How much did you refund in Paystack, in naira? (for example 5000). Access is taken back in the same share of the plan's days.");
      if (!text) return;
      const kobo = parseNairaToKobo(text);
      if (kobo === null) {
        setDone("That is not an amount. Use naira, for example 5000 or 5,000.50.");
        return;
      }
      amountKobo = kobo;
    }
    const reason = window.prompt("Why is this being refunded? (kept in the audit log). This takes back the access; refund the money in Paystack.");
    if (!reason || reason.trim().length < 3) return;
    const r = await grant.run(() => refundPayment(reference, reason.trim(), amountKobo, override));
    if (!r.ok) return;
    setDone(part ? "Partial refund recorded and the matching access taken back." : "Access taken back for that payment.");
    const list = await adminPayments();
    if (list.ok) setPayments(list.data.payments);
    if (found?.user?.email) await lookup(found.user.email);
  }

  async function onRemind() {
    setReminders(null);
    const r = await remind.run(() => adminSendReminders());
    if (r.ok)
      setReminders(`Sent ${r.data.sent}. ${r.data.failed} failed (will retry). ${r.data.skipped} not due or already sent.`);
  }

  return (
    <div className="grid max-w-4xl gap-4">
      <Card title="1. Find the customer">
        <form onSubmit={onFind} className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <Field label="Customer's email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} hint="The email they registered with. They must have an account first." />
          </div>
          <button type="submit" disabled={find.pending} className={buttonStyles({ variant: "secondary" })}>
            {find.pending ? "Looking…" : "Find"}
          </button>
        </form>
        {find.error ? <div className="mt-3"><Notice tone="error">{find.error}</Notice></div> : null}
        {found && !found.found ? (
          <div className="mt-3"><Notice tone="error">No account has that email. Ask them to register first.</Notice></div>
        ) : null}
        {found?.found && found.user && found.entitlement ? (
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted">Name</dt>
              <dd className="font-semibold">{found.user.name}</dd>
            </div>
            <div>
              <dt className="text-muted">Now</dt>
              <dd className="font-semibold">{describeEntitlement(found.entitlement).headline}</dd>
            </div>
            <div>
              <dt className="text-muted">Institution</dt>
              <dd className="font-semibold">
                {found.institution
                  ? `${found.institution.name} (${found.institution.seats_used} of ${found.institution.seats_allowed} logins${found.institution.ends_at ? `, until ${formatDate(found.institution.ends_at)}` : ""})`
                  : "None"}
              </dd>
            </div>
          </dl>
        ) : null}
      </Card>

      {found?.found ? (
        <Card title="2. Record the payment">
          <form onSubmit={onGrant} className="space-y-4">
            {grant.error ? <Notice tone="error">{grant.error}</Notice> : null}
            {done ? <Notice tone="success">{done}</Notice> : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm font-medium">
                Plan
                <select
                  value={planCode}
                  onChange={(e) => setPlanCode(e.target.value)}
                  className="mt-1 block min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-base text-fg"
                >
                  {plans.plans.map((p) => (
                    <option key={p.code} value={p.code}>
                      {p.name} ({formatNaira(p.monthly_kobo)} / month)
                    </option>
                  ))}
                </select>
              </label>
              <Field label="Months paid for" type="number" inputMode="numeric" min={1} max={plans.max_months} required value={months}
                onChange={(e) => setMonths(Math.min(plans.max_months, Math.max(1, Number(e.target.value) || 1)))} />
            </div>
            {needsName ? (
              <Field label="Institution name" required maxLength={120} value={institutionName} onChange={(e) => setInstitutionName(e.target.value)}
                hint="They become its manager and can then create the logins themselves." />
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="font-bold">Amount received: {plan ? formatNaira(plan.monthly_kobo * months) : ""}</p>
              <button type="submit" disabled={grant.pending} className={buttonStyles()}>
                {grant.pending ? "Recording…" : "Record payment and give access"}
              </button>
            </div>
            <p className="text-sm text-muted">Only record money you have seen in your bank account. The amount follows the plan price; it cannot be edited.</p>
          </form>
        </Card>
      ) : null}

      <Card title="Recent payments">
        {payments.length === 0 ? (
          <p className="text-sm text-muted">No payments yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-4 font-medium">Customer</th>
                  <th className="py-1 pr-4 font-medium">Plan</th>
                  <th className="py-1 pr-4 font-medium">Amount</th>
                  <th className="py-1 pr-4 font-medium">How</th>
                  <th className="py-1 pr-4 font-medium">Status</th>
                  <th className="py-1 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((p) => (
                  <tr key={p.reference} className="border-t border-line">
                    <td className="py-2 pr-4">{p.name}<span className="block text-xs text-muted">{p.email}</span></td>
                    <td className="py-2 pr-4">{plans.plans.find((x) => x.code === p.plan_code)?.name ?? p.plan_code}, {p.months}m</td>
                    <td className="py-2 pr-4">{formatNaira(p.amount_kobo)}</td>
                    <td className="py-2 pr-4">{p.reference.startsWith("manual_") ? "Recorded by admin" : "Paystack"}</td>
                    <td className="py-2 pr-4">{p.status === "success" ? "Paid" : p.status === "pending" ? "Not completed" : p.status === "refunded" ? "Refunded" : "Failed"}
                      {p.status === "success" && (p.refunded_kobo ?? 0) > 0 ? (
                        <span className="block text-xs text-muted">{formatNaira(p.refunded_kobo ?? 0)} refunded</span>
                      ) : null}
                      {p.status === "success" ? (
                        <>
                          <button type="button" className="ml-2 text-xs underline underline-offset-4" onClick={() => void onRefund(p.reference)}>Refund the rest</button>
                          {p.kind !== "upgrade" ? (
                            <button type="button" className="ml-2 text-xs underline underline-offset-4" onClick={() => void onRefund(p.reference, true)}>Part refund</button>
                          ) : null}
                        </>
                      ) : null}
                    </td>
                    <td className="py-2 text-muted">{formatDate(p.paid_at ?? p.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Plan-ending emails">
        <p className="max-w-[62ch] text-sm text-muted">
          These go out by themselves every morning at 08:00 (Nigeria time): 7 days, 3 days and 1 day before a plan
          ends, and once when it has ended. Use the button to run it now, for example to check that Resend works.
          Nobody receives the same email twice.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => void onRemind()} disabled={remind.pending} className={buttonStyles({ variant: "secondary" })}>
            {remind.pending ? "Sending…" : "Send plan-ending emails now"}
          </button>
          {reminders ? <span className="text-sm" role="status">{reminders}</span> : null}
        </div>
        {remind.error ? <div className="mt-3"><Notice tone="error">{remind.error}</Notice></div> : null}
      </Card>
    </div>
  );
}
