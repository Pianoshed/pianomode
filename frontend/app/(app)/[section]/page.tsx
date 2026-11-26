import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { Notice } from "@/components/ui/Notice";
import { canAccess, findNavItem } from "@/lib/nav";
import { getCurrentUser } from "@/lib/user";

type Props = { params: Promise<{ section: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const item = findNavItem((await params).section);
  return { title: item?.label ?? "Not found" };
}

/**
 * Catch-all for areas that have no page of their own yet. Each area replaces this by adding a
 * folder with the same name under app/(app)/ (static routes win over this dynamic one).
 * Restricted areas return "not found" to users without the role.
 */
export default async function UnbuiltSectionPage({ params }: Props) {
  const item = findNavItem((await params).section);
  const user = await getCurrentUser();
  if (!item || !canAccess(item, user)) notFound();

  return (
    <>
      <PageHeader title={item.label} description={item.summary} />
      <Notice>This area has not been built yet.</Notice>
    </>
  );
}
