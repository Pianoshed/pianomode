import type { AuditAction, PersonKind } from "@/lib/admin/types";

export const KIND_LABEL: Record<PersonKind, string> = {
  individual: "Individual",
  institution_owner: "Institution manager",
  seat: "Institution login",
};

const ACTION_LABEL: Record<string, string> = {
  account_closed: "Closed the account",
  account_reopened: "Reopened the account",
  signed_out_everywhere: "Signed the person out everywhere",
  role_granted: "Gave a role",
  role_removed: "Removed a role",
  two_factor_reset: "Reset two-factor sign-in",
  payment_recorded: "Recorded a payment made outside Paystack",
  payment_refunded: "Refunded a payment (access taken back)",
  refund_needs_review: "A refund arrived that needs a person to check it",
};

/** One line in plain words for the audit log. */
export function describeAction(a: Pick<AuditAction, "action" | "detail">): string {
  const base = ACTION_LABEL[a.action] ?? a.action.replace(/_/g, " ");
  const d = a.detail;
  const bits: string[] = [];
  if (typeof d.role === "string") bits.push(d.role);
  if (typeof d.plan === "string") bits.push(`${d.plan}${typeof d.months === "number" ? `, ${d.months} month${d.months === 1 ? "" : "s"}` : ""}`);
  if (typeof d.reason === "string") bits.push(`reason: ${d.reason}`);
  if (typeof d.reference === "string") bits.push(`ref ${d.reference}`);
  return bits.length ? `${base} (${bits.join("; ")})` : base;
}
