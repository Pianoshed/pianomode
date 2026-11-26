"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Field } from "@/components/auth/Field";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { forgetCard, getCard, getInstitution, getUpgradeQuote, setAutoRenew, startCheckout } from "@/lib/billing/api";
import { describeEntitlement, formatDate, formatNaira } from "@/lib/billing/format";
import type { BillingStatus, CardStatus, Payment, PlansResponse } from "@/lib/billing/types";

const STATUS_LABEL: Record<string, string> = { success: "Paid", pending: "Not completed", failed: "Failed", refunded: "Refunded" };

export function SubscriptionPanel({
  status,
  plans,
  payments,
  notice,
}: {
  status: BillingStatus;
  plans: PlansResponse;
  payments: Payment[];
  notice?: string;
}) {
  const { pending, error, run } = useAction();
  const [planCode, setPlanCode] = useState(plans.plans[0]?.code ?? "individual");
  const [months, setMonths] = useState(1);
  const [institutionName, setInstitutionName] = useState("");
  const [renewAuto, setRenewAuto] = useState(false);

  // Automatic renewal is opt-in and only offered when the server has it switched on.
  const [card, setCard] = useState<CardStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const r = await getCard();
      if (r.ok && !cancelled) setCard(r.data);
    })();
    return () => { cancelled = true; };
  }, []);

  async function onToggleRenew(enabled: boolean) {
    const r = await run(() => setAutoRenew(enabled));
    if (r.ok) setCard(r.data);
  }
  async function onForgetCard() {
    const r = await run(() => forgetCard());
    if (r.ok) setCard((c) => (c ? { ...c, has_card: false, auto_renew: false, brand: null, last4: null, failures: 0 } : c));
  }

  // An institution manager with a running plan can move up to a bigger one for the rest of the period.
  const [upgrade, setUpgrade] = useState<{ plan: string; name: string; amount: number; days: number; seats: number } | null>(null);
  useEffect(() => {
    if (status.institution_role !== "owner") return;
    let cancelled = false;
    void (async () => {
      const inst = await getInstitution();
      if (!inst.ok || !inst.data.subscription_live) return;
      const cur = plans.plans.find((p) => p.code === inst.data.plan_code);
      const next = plans.plans.filter((p) => p.kind === "institution" && (p.seats ?? 0) > (cur?.seats ?? 0)).sort((a, b) => (a.seats ?? 0) - (b.seats ?? 0))[0];
      if (!cur || !next) return;
      const q = await getUpgradeQuote(next.code);
      if (q.ok && !cancelled) setUpgrade({ plan: next.code, name: next.name, amount: q.data.amount_kobo, days: q.data.days_left, seats: q.data.seats });
    })();
    return () => { cancelled = true; };
  }, [status.institution_role, plans.plans]);

  async function onUpgrade() {
    if (!upgrade) return;
    const r = await run(() => startCheckout({ plan: upgrade.plan, months: 1 }));
    if (r.ok) window.location.assign(r.data.authorization_url);
  }

  const text = describeEntitlement(status.entitlement);
  const plan = plans.plans.find((p) => p.code === planCode);
  const isInstitution = plan?.kind === "institution";
  const needsName = isInstitution && status.institution_role !== "owner";
  const total = plan ? plan.monthly_kobo * months : 0;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!plan) return;
    const r = await run(() =>
      startCheckout({
        plan: plan.code,
        months,
        ...(needsName ? { institution_name: institutionName } : {}),
        ...(card?.available && renewAuto ? { save_card: true } : {}),
      }),
    );
    if (r.ok) window.location.assign(r.data.authorization_url);
  }

  return (
    <div className="grid max-w-3xl gap-4">
      {notice ? <Notice tone="info">{notice}</Notice> : null}
      <Card title="Your plan">
        <p className="text-lg font-semibold">{text.headline}</p>
        <p className="mt-1 max-w-[60ch] text-sm text-muted">{text.detail}</p>
        {status.institution_role === "owner" ? (
          <p className="mt-3 text-sm">
            You manage an institution. <a className="underline underline-offset-4" href="/institution">Manage logins</a>
          </p>
        ) : null}
      </Card>

      {upgrade ? (
        <Card title="Upgrade your institution plan">
          <p className="max-w-[60ch] text-sm">
            Need more people? Move up to <strong>{upgrade.name}</strong> ({upgrade.seats} logins) now. You pay only the
            difference for the {upgrade.days} day{upgrade.days === 1 ? "" : "s"} left in this period, and the end date does not change.
          </p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p className="text-lg font-bold">{formatNaira(upgrade.amount)}</p>
            <button type="button" disabled={pending} onClick={() => void onUpgrade()} className={buttonStyles()}>
              {pending ? "Opening Paystack…" : "Upgrade with Paystack"}
            </button>
          </div>
        </Card>
      ) : null}

      {card?.available && status.can_purchase && card.has_card ? (
        <Card title="Automatic renewal">
          <p className="max-w-[60ch] text-sm">
            {card.auto_renew
              ? `Your plan renews by itself. About a day before it ends we charge one more month to your ${card.brand ?? "card"} ending ${card.last4}, and email you a receipt.`
              : `Automatic renewal is off. Your plan will simply end on its date. Your ${card.brand ?? "card"} ending ${card.last4} is still saved.`}
          </p>
          {card.failures > 0 && card.auto_renew ? (
            <Notice tone="error">The last renewal did not go through. Check that the card has enough money, or pay below with another card.</Notice>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" disabled={pending} onClick={() => void onToggleRenew(!card.auto_renew)} className={buttonStyles()}>
              {card.auto_renew ? "Turn off automatic renewal" : "Turn on automatic renewal"}
            </button>
            <button type="button" disabled={pending} onClick={() => void onForgetCard()} className={buttonStyles({ variant: "secondary" })}>
              Forget this card
            </button>
          </div>
        </Card>
      ) : null}

      {!status.can_purchase ? (
        <Notice>Your access is paid for by your institution, so there is nothing to buy here.</Notice>
      ) : (
        <Card title={status.entitlement.has_access && status.entitlement.source !== "trial" ? "Add time" : "Choose a plan"}>
          <form onSubmit={onSubmit} className="space-y-5">
            {error ? <Notice tone="error">{error}</Notice> : null}
            <fieldset className="grid gap-3 sm:grid-cols-3">
              <legend className="sr-only">Plan</legend>
              {plans.plans.map((p) => (
                <label
                  key={p.code}
                  className={`flex cursor-pointer flex-col gap-1 rounded-lg border p-4 has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 ${
                    p.code === planCode ? "border-accent bg-accent-soft" : "border-line bg-surface hover:bg-surface-2"
                  }`}
                >
                  <input
                    type="radio"
                    name="plan"
                    value={p.code}
                    checked={p.code === planCode}
                    onChange={() => setPlanCode(p.code)}
                    className="sr-only"
                  />
                  <span className="text-sm font-semibold">{p.name}</span>
                  <span className="text-2xl font-bold">{formatNaira(p.monthly_kobo)}</span>
                  <span className="text-sm text-muted">
                    per month
                    {p.seats ? `, up to ${p.seats} people each with their own login` : ", just for you"}
                  </span>
                </label>
              ))}
            </fieldset>

            {needsName ? (
              <Field
                label="Institution name"
                required
                maxLength={120}
                value={institutionName}
                onChange={(e) => setInstitutionName(e.target.value)}
                hint="Shown to you when you manage logins. After paying you create a login for each person."
              />
            ) : null}

            <Field
              label="Months to pay for"
              type="number"
              inputMode="numeric"
              min={1}
              max={plans.max_months}
              required
              value={months}
              onChange={(e) => setMonths(Math.min(plans.max_months, Math.max(1, Number(e.target.value) || 1)))}
              hint={`Each month adds 30 days. Up to ${plans.max_months} at a time.${card?.available ? "" : " Nothing is charged again automatically."}`}
            />

            {card?.available ? (
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={renewAuto}
                  onChange={(e) => setRenewAuto(e.target.checked)}
                  className="mt-1 h-4 w-4"
                />
                <span className="max-w-[60ch]">
                  <strong>Renew automatically.</strong> If you pay by card, we keep it (we never see the number) and charge one month at the
                  then-current price about a day before your plan ends. We email you before and after each charge. You can turn it off or
                  forget the card here at any time. Bank transfer and USSD payments cannot renew.
                </span>
              </label>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-lg font-bold" aria-live="polite">
                Total {formatNaira(total)}
              </p>
              <button type="submit" disabled={pending || !plan} className={buttonStyles({ size: "lg" })}>
                {pending ? "Opening Paystack…" : "Pay with Paystack"}
              </button>
            </div>
            <p className="text-sm text-muted">
              You pay on Paystack&apos;s own page by card, bank transfer or USSD. We never see your card details. See the <a className="underline underline-offset-4" href="/refunds">refund policy</a>.
            </p>
          </form>
        </Card>
      )}

      {payments.length > 0 ? (
        <Card title="Payment history">
          <ul className="divide-y divide-line text-sm">
            {payments.map((p) => (
              <li key={p.reference} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                <span>
                  {p.kind === "upgrade" ? "Upgrade to " : p.kind === "renewal" ? "Automatic renewal: " : ""}{plans.plans.find((x) => x.code === p.plan_code)?.name ?? p.plan_code}{p.kind === "upgrade" ? "" : `, ${p.months} month${p.months === 1 ? "" : "s"}`}
                </span>
                <span className="text-muted">
                  {formatNaira(p.amount_kobo)} · {STATUS_LABEL[p.status] ?? p.status} · {formatDate(p.paid_at ?? p.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
