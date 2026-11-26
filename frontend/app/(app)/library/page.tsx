import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { LibraryView } from "@/components/library/LibraryView";
import { Notice } from "@/components/ui/Notice";
import { getBillingStatus } from "@/lib/billing/server";
import { getLibrary } from "@/lib/library/server";

export const metadata: Metadata = { title: "My Library" };
export const dynamic = "force-dynamic";

export default async function LibraryPage() {
  const [library, billing] = await Promise.all([getLibrary(), getBillingStatus()]);
  return (
    <>
      <PageHeader title="My Library" description="Your saved MIDI projects, audio analyses and chord progressions." />
      {library ? (
        <LibraryView initial={library} canOpen={billing ? billing.entitlement.has_access : true} />
      ) : (
        <Notice tone="error">Could not load your library. Refresh the page in a moment.</Notice>
      )}
    </>
  );
}
