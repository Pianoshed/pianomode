import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { SubscriptionPanel } from "@/components/billing/SubscriptionPanel";
import { Notice } from "@/components/ui/Notice";
import { getBillingStatus, getPayments, getPlans } from "@/lib/billing/server";

export const metadata: Metadata = { title: "Subscription" };
export const dynamic = "force-dynamic";

const NOTICES: Record<string, string> = {
  required: "Your access has ended. Choose a plan to carry on with lessons, practice and the studio tools.",
};

export default async function SubscriptionPage({ searchParams }: { searchParams: Promise<{ reason?: string }> }) {
  const { reason } = await searchParams;
  const [status, plans, payments] = await Promise.all([getBillingStatus(), getPlans(), getPayments()]);
  return (
    <>
      <PageHeader title="Subscription" description="Your plan, trial time and payments." />
      {status && plans ? (
        <SubscriptionPanel status={status} plans={plans} payments={payments} notice={reason ? NOTICES[reason] : undefined} />
      ) : (
        <Notice tone="error">Could not load your plan. Refresh the page in a moment.</Notice>
      )}
    </>
  );
}
