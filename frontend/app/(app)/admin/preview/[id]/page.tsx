import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MovementPlayer } from "@/components/movements/MovementPlayer";
import { PageHeader } from "@/components/PageHeader";
import { canAccess, findNavItem } from "@/lib/nav";
import { getCurrentUser } from "@/lib/user";

type Props = { params: Promise<{ id: string }> };

export const metadata: Metadata = { title: "Preview movement" };

export default async function PreviewPage({ params }: Props) {
  const item = findNavItem("admin");
  const user = await getCurrentUser();
  if (!item || !canAccess(item, user)) notFound();
  const { id } = await params;
  return (
    <>
      <PageHeader title="Preview" description="How learners will see this movement, before it is published." />
      <MovementPlayer previewId={id} />
    </>
  );
}
