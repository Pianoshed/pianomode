import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { PracticeRoom } from "@/components/practice/PracticeRoom";
import { canAccess, findNavItem } from "@/lib/nav";
import { getCurrentUser } from "@/lib/user";

export const metadata: Metadata = { title: "Practice Room" };

export default async function PracticePage() {
  const item = findNavItem("practice");
  const user = await getCurrentUser();
  if (!item || !canAccess(item, user)) notFound();
  return (
    <>
      <PageHeader title={item.label} description={item.summary} />
      <PracticeRoom />
    </>
  );
}
