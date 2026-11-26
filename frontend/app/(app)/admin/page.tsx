import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { LessonAdmin } from "@/components/admin/LessonAdmin";
import { MovementAdmin } from "@/components/admin/MovementAdmin";
import { ScaleAdmin } from "@/components/admin/ScaleAdmin";
import { PageHeader } from "@/components/PageHeader";
import { canAccess, findNavItem } from "@/lib/nav";
import { getCurrentUser, hasAnyRole } from "@/lib/user";

export const metadata: Metadata = { title: "Content Admin" };

/** Restricted to educators and admins; the API enforces the same rule on every call. */
export default async function AdminPage() {
  const item = findNavItem("admin");
  const user = await getCurrentUser();
  if (!item || !canAccess(item, user)) notFound();
  return (
    <>
      <PageHeader title={item.label} description={item.summary} />
      <MovementAdmin />
      <div className="mt-12 border-t border-line pt-8">
        <LessonAdmin />
      </div>
      {hasAnyRole(user, ["admin"]) ? (
        <div className="mt-12 border-t border-line pt-8">
          <ScaleAdmin />
        </div>
      ) : null}
    </>
  );
}
