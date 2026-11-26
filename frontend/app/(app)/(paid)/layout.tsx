import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { getBillingStatus } from "@/lib/billing/server";

/**
 * Everything that needs a plan lives under this group (the folder name is not part of any URL).
 * Dashboard, Subscription, Institution, Settings and Admin sit outside it, so a person whose plan
 * has ended can still get to the page that fixes that. The API refuses these tools too (HTTP 402);
 * this redirect only saves people from a screen full of errors.
 */
export const dynamic = "force-dynamic";

export default async function PaidLayout({ children }: { children: ReactNode }) {
  const status = await getBillingStatus();
  // If the status cannot be fetched, show the page: the API still enforces access on every call.
  if (status && !status.entitlement.has_access) redirect("/subscription?reason=required");
  return children;
}
