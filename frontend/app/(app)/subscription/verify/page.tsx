import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { VerifyPayment } from "@/components/billing/VerifyPayment";
import { Notice } from "@/components/ui/Notice";

export const metadata: Metadata = { title: "Payment" };
export const dynamic = "force-dynamic";

export default async function VerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ reference?: string; trxref?: string }>;
}) {
  const sp = await searchParams;
  const reference = sp.reference ?? sp.trxref;
  return (
    <>
      <PageHeader title="Payment" />
      <div className="max-w-xl">
        {reference ? (
          <VerifyPayment reference={reference} />
        ) : (
          <Notice tone="error">
            No payment was found in this link. <Link href="/subscription" className="underline underline-offset-4">Back to Subscription</Link>
          </Notice>
        )}
      </div>
    </>
  );
}
