import type { Metadata } from "next";
import { Suspense } from "react";
import { TheoryPractice } from "@/components/theory/TheoryPractice";
import { PageHeader } from "@/components/PageHeader";
import { findNavItem } from "@/lib/nav";

export const metadata: Metadata = { title: "Music Theory" };

export default function TheoryPage() {
  const item = findNavItem("theory");
  return (
    <>
      <PageHeader title={item?.label ?? "Music Theory"} description={item?.summary} />
      <Suspense fallback={null}>
        <TheoryPractice />
      </Suspense>
    </>
  );
}
