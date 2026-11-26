import type { Metadata } from "next";
import { MovementBrowser } from "@/components/movements/MovementBrowser";
import { PageHeader } from "@/components/PageHeader";
import { findNavItem } from "@/lib/nav";

export const metadata: Metadata = { title: "Chord Progressions" };

export default function ProgressionsPage() {
  const item = findNavItem("progressions");
  return (
    <>
      <PageHeader title={item?.label ?? "Chord Progressions"} description={item?.summary} />
      <MovementBrowser />
    </>
  );
}
