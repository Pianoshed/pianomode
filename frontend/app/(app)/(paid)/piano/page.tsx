import type { Metadata } from "next";
import { PianoWorkspace } from "@/components/piano/PianoWorkspace";
import { PageHeader } from "@/components/PageHeader";
import { findNavItem } from "@/lib/nav";

export const metadata: Metadata = { title: "Interactive Piano" };

export default function PianoPage() {
  const item = findNavItem("piano");
  return (
    <>
      <PageHeader title={item?.label ?? "Interactive Piano"} description={item?.summary} />
      <PianoWorkspace />
    </>
  );
}
