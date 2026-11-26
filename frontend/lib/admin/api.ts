import { api } from "@/lib/api";
import type { AuditAction, PersonDetail, PersonRow } from "@/lib/admin/types";

export const listPeople = (q: string, role: string, offset: number, limit = 25) =>
  api<{ users: PersonRow[]; total: number }>(
    `/api/v1/admin/users?${new URLSearchParams({ q, role, offset: String(offset), limit: String(limit) })}`,
  );
export const getPerson = (id: string) => api<PersonDetail>(`/api/v1/admin/users/${id}`);
export const personAction = (id: string, action: "close" | "reopen" | "sign-out" | "reset-two-factor") =>
  api<void>(`/api/v1/admin/users/${id}/${action}`, { method: "POST" });
export const changeRole = (id: string, role: "educator" | "admin", grant: boolean) =>
  api<void>(`/api/v1/admin/users/${id}/roles`, { method: "POST", body: { role, grant } });
export const getAudit = (userId?: string) =>
  api<{ actions: AuditAction[] }>(`/api/v1/admin/audit${userId ? `?user_id=${userId}` : ""}`);
/** Leave `amountKobo` out to refund everything that is left; give it for a partial refund. */
export const refundPayment = (reference: string, reason: string, amountKobo?: number, override = false) =>
  api<unknown>(`/api/v1/admin/billing/payments/${reference}/refund`, {
    method: "POST",
    body: {
      reason,
      ...(amountKobo === undefined ? {} : { amount_kobo: amountKobo }),
      ...(override ? { override: true } : {}),
    },
  });

export type RefundCheck = {
  days_since_paid: number;
  window_days: number;
  outside_window: boolean;
  prior_refunds: number;
  repeat: boolean;
  needs_override: boolean;
};

/** Is this refund late, or is the person a repeat? Asked before recording it. */
export const refundCheck = (reference: string) =>
  api<RefundCheck>(`/api/v1/admin/billing/payments/${reference}/refund-check`);

/** The warning shown before an unusual refund, or null when nothing is unusual. */
export function refundWarning(c: RefundCheck): string | null {
  const parts: string[] = [];
  if (c.outside_window)
    parts.push(`This was paid ${c.days_since_paid} days ago; refunds are normally made within ${c.window_days} days.`);
  if (c.repeat) parts.push(`This person has already had ${c.prior_refunds} other payments refunded.`);
  return parts.length ? `${parts.join(" ")}\n\nRefund it anyway? This is recorded in the audit log.` : null;
}
