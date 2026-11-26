"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { verifyPayment } from "@/lib/billing/api";
import type { Payment } from "@/lib/billing/types";

type State =
  | { kind: "checking" }
  | { kind: "done"; payment: Payment; isInstitution: boolean }
  | { kind: "error"; message: string };

/** The page Paystack sends the person back to. Asks the server to confirm the payment. */
export function VerifyPayment({ reference }: { reference: string }) {
  const [state, setState] = useState<State>({ kind: "checking" });
  const started = useRef(false);

  const check = useCallback(async () => {
    setState({ kind: "checking" });
    const r = await verifyPayment(reference);
    if (!r.ok) return setState({ kind: "error", message: r.message });
    setState({ kind: "done", payment: r.data.payment, isInstitution: r.data.payment.plan_code.startsWith("institution") });
  }, [reference]);

  useEffect(() => {
    if (started.current) return; // React strict mode runs effects twice in development
    started.current = true;
    void check();
  }, [check]);

  if (state.kind === "checking") return <Notice>Confirming your payment with Paystack…</Notice>;
  if (state.kind === "error")
    return (
      <div className="space-y-4">
        <Notice tone="error">{state.message}</Notice>
        <p className="max-w-[60ch] text-sm text-muted">
          If money left your account, do not pay again. It can take a few minutes to reach us, and your access starts
          by itself when it does.
        </p>
        <button type="button" onClick={() => void check()} className={buttonStyles({ variant: "secondary" })}>
          Check again
        </button>
      </div>
    );

  const { payment, isInstitution } = state;
  if (payment.status === "success")
    return (
      <div className="space-y-4">
        <Notice tone="success">Payment received. Thank you.</Notice>
        <div className="flex flex-wrap gap-3">
          <Link href={isInstitution ? "/institution" : "/dashboard"} className={buttonStyles()}>
            {isInstitution ? "Create logins for your people" : "Start playing"}
          </Link>
          <Link href="/subscription" className={buttonStyles({ variant: "secondary" })}>
            View my plan
          </Link>
        </div>
      </div>
    );
  if (payment.status === "pending")
    return (
      <div className="space-y-4">
        <Notice>This payment has not been completed yet. If you paid by bank transfer it can take a few minutes.</Notice>
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={() => void check()} className={buttonStyles({ variant: "secondary" })}>
            Check again
          </button>
          <Link href="/subscription" className={buttonStyles({ variant: "ghost" })}>
            Back to plans
          </Link>
        </div>
      </div>
    );
  return (
    <div className="space-y-4">
      <Notice tone="error">This payment did not go through, so nothing was added to your plan.</Notice>
      <Link href="/subscription" className={buttonStyles()}>
        Try again
      </Link>
    </div>
  );
}
