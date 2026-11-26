import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { BillingAdmin } from "@/components/billing/BillingAdmin";
import { Notice } from "@/components/ui/Notice";
import { getAdminPayments, getPlans } from "@/lib/billing/server";
import { canAccess, findNavItem } from "@/lib/nav";
import { getCurrentUser } from "@/lib/user";

export const metadata: Metadata = { title: "Billing Admin" };
export const dynamic = "force-dynamic";

export default async function BillingAdminPage() {
  const user = await getCurrentUser();
  const item = findNavItem("billing-admin");
  if (!item || !canAccess(item, user)) notFound(); // the API refuses non-admins as well
  const [plans, payments] = await Promise.all([getPlans(), getAdminPayments()]);
  return (
    <>
      <PageHeader title="Billing Admin" description="Record bank transfers, look up customers and check payments." />
      {plans ? <BillingAdmin plans={plans} initialPayments={payments} /> : <Notice tone="error">Could not load plans. Refresh in a moment.</Notice>}
    </>
  );
}
