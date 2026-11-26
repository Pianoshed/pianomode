import type { AdminPayment, Entitlement } from "@/lib/billing/types";

export type PersonKind = "individual" | "institution_owner" | "seat";

export type PersonRow = {
  id: string;
  name: string;
  email: string | null;
  login_id: string | null;
  roles: string[];
  is_active: boolean;
  email_verified: boolean;
  two_factor_enabled: boolean;
  kind: PersonKind;
  created_at: string;
};
export type PersonDetail = PersonRow & {
  entitlement: Entitlement;
  institution_name: string | null;
  library_items: number;
  library_bytes: number;
  active_sessions: number;
  payments: AdminPayment[];
};
export type AuditAction = {
  id: string;
  actor_email: string;
  action: string;
  target_label: string;
  target_user_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};
