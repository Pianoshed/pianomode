import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { InstitutionManager } from "@/components/institution/InstitutionManager";
import { getInstitutionOverview } from "@/lib/billing/server";

export const metadata: Metadata = { title: "Institution logins" };
export const dynamic = "force-dynamic";

export default async function InstitutionPage() {
  const overview = await getInstitutionOverview();
  if (!overview) notFound(); // not an institution manager
  return (
    <>
      <PageHeader title="Institution logins" description="Give each person their own login. One person, one login." />
      <InstitutionManager initial={overview} />
    </>
  );
}
