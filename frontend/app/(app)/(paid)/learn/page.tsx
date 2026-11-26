import type { Metadata } from "next";
import { LessonList } from "@/components/lessons/LessonList";
import { PageHeader } from "@/components/PageHeader";
import { findNavItem } from "@/lib/nav";

export const metadata: Metadata = { title: "Learn" };

export default function LearnPage() {
  const item = findNavItem("learn");
  return (
    <>
      <PageHeader title={item?.label ?? "Learn"} description={item?.summary} />
      <LessonList />
    </>
  );
}
