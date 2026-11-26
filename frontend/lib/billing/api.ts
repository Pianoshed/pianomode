import { api } from "@/lib/api";
import type {
  AdminLookup,
  AdminPayment,
  CardStatus,
  Credential,
  Entitlement,
  InstitutionOverview,
  Payment,
} from "@/lib/billing/types";

export const startCheckout = (body: {
  plan: string;
  months: number;
  institution_name?: string;
  save_card?: boolean;
}) =>
  api<{ reference: string; authorization_url: string; amount_kobo: number }>("/api/v1/billing/checkout", {
    method: "POST",
    body,
  });

export const verifyPayment = (reference: string) =>
  api<{ payment: Payment; entitlement: Entitlement }>("/api/v1/billing/verify", {
    method: "POST",
    body: { reference },
  });

export const getInstitution = () => api<InstitutionOverview>("/api/v1/institution");

export const createSeats = (names: string[]) =>
  api<{ credentials: Credential[] }>("/api/v1/institution/seats", { method: "POST", body: { names } });

export const resetSeatPassword = (id: string) =>
  api<{ credentials: Credential[] }>(`/api/v1/institution/seats/${id}/reset-password`, { method: "POST" });

export const setSeatActive = (id: string, active: boolean) =>
  api<void>(`/api/v1/institution/seats/${id}/${active ? "activate" : "deactivate"}`, { method: "POST" });

export const getUpgradeQuote = (plan: string) =>
  api<{ plan: string; amount_kobo: number; days_left: number; from_plan: string; seats: number }>(
    `/api/v1/billing/upgrade-quote?plan=${encodeURIComponent(plan)}`,
  );

export const adminLookup = (email: string) =>
  api<AdminLookup>(`/api/v1/admin/billing/lookup?email=${encodeURIComponent(email)}`);

export const adminGrant = (body: { email: string; plan: string; months: number; institution_name?: string }) =>
  api<Payment>("/api/v1/admin/billing/grant", { method: "POST", body });

export const adminPayments = () => api<{ payments: AdminPayment[] }>("/api/v1/admin/billing/payments");

export const adminSendReminders = () =>
  api<{ sent: number; failed: number; skipped: number }>("/api/v1/admin/billing/send-reminders", { method: "POST" });

export const setReminderEmails = (on: boolean) =>
  api<unknown>("/api/v1/auth/me/preferences", { method: "PATCH", body: { reminder_emails: on } });

export const getCard = () => api<CardStatus>("/api/v1/billing/card");

export const setAutoRenew = (enabled: boolean) =>
  api<CardStatus>("/api/v1/billing/auto-renew", { method: "POST", body: { enabled } });

export const forgetCard = () => api<void>("/api/v1/billing/card", { method: "DELETE" });
