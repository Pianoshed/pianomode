export type Plan = {
  code: string;
  name: string;
  kind: "individual" | "institution";
  seats: number | null;
  monthly_kobo: number;
};
export type PlansResponse = { currency: string; max_months: number; plans: Plan[] };

export type Entitlement = {
  has_access: boolean;
  source: "staff" | "individual" | "trial" | "institution" | "none";
  plan_code: string | null;
  ends_at: string | null;
  days_left: number | null;
  institution_name: string | null;
  reason: string;
};
export type BillingStatus = {
  entitlement: Entitlement;
  can_purchase: boolean;
  institution_role: "owner" | "seat" | null;
};

export type Payment = {
  reference: string;
  plan_code: string;
  months: number;
  amount_kobo: number;
  currency: string;
  status: string;
  kind?: "purchase" | "upgrade" | "renewal";
  refunded_kobo?: number;
  created_at: string;
  paid_at: string | null;
};

export type Seat = {
  id: string;
  login_id: string;
  name: string;
  active: boolean;
  last_login_at: string | null;
};
export type InstitutionOverview = {
  name: string;
  code: string;
  plan_code: string | null;
  seats_allowed: number;
  seats_used: number;
  ends_at: string | null;
  subscription_live: boolean;
  seats: Seat[];
};
export type Credential = { id: string; login_id: string; name: string; password: string };

export type AdminLookup = {
  found: boolean;
  user: { name: string; email: string; roles: string[]; is_active: boolean } | null;
  entitlement: Entitlement | null;
  institution: {
    name: string;
    code: string;
    plan_code: string | null;
    seats_allowed: number;
    seats_used: number;
    ends_at: string | null;
  } | null;
};
export type AdminPayment = Payment & { email: string | null; name: string };

export type CardStatus = {
  available: boolean;
  has_card: boolean;
  brand: string | null;
  last4: string | null;
  exp_month: string | null;
  exp_year: string | null;
  auto_renew: boolean;
  failures: number;
};
