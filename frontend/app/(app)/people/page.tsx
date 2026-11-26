import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { PeopleAdmin } from "@/components/admin/PeopleAdmin";
import { canAccess, findNavItem } from "@/lib/nav";
import { getCurrentUser } from "@/lib/user";

export const metadata: Metadata = { title: "People" };
export const dynamic = "force-dynamic";

export default async function PeoplePage() {
  const user = await getCurrentUser();
  const item = findNavItem("people");
  if (!item || !canAccess(item, user)) notFound(); // the API refuses non-admins as well
  return (
    <>
      <PageHeader title="People" description="Find an account, see its plan, close it, change roles, and read the audit log." />
      <PeopleAdmin />
    </>
  );
}
