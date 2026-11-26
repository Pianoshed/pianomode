import { apiBase, apiHeaders } from "@/lib/server-api";
import type {
  AdminPayment,
  BillingStatus,
  InstitutionOverview,
  Payment,
  PlansResponse,
} from "@/lib/billing/types";

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${apiBase()}${path}`, { headers: await apiHeaders(), cache: "no-store" });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

/** Server-only. Null when the API cannot be reached; callers should then not block the person. */
export const getBillingStatus = () => get<BillingStatus>("/api/v1/billing/status");
export const getPlans = () => get<PlansResponse>("/api/v1/billing/plans");
export const getPayments = async () => (await get<{ payments: Payment[] }>("/api/v1/billing/payments"))?.payments ?? [];
export const getInstitutionOverview = () => get<InstitutionOverview>("/api/v1/institution");

export const getAdminPayments = async () =>
  (await get<{ payments: AdminPayment[] }>("/api/v1/admin/billing/payments"))?.payments ?? [];
