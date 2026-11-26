import type { Metadata } from "next";
import { MidiStudio } from "@/components/midi/MidiStudio";
import { PageHeader } from "@/components/PageHeader";
import { findNavItem } from "@/lib/nav";

export const metadata: Metadata = { title: "MIDI Studio" };

const ID = /^[0-9a-f-]{36}$/i;

export default async function MidiPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const item = findNavItem("midi");
  const { project } = await searchParams;
  return (
    <>
      <PageHeader title={item?.label ?? "MIDI Studio"} description={item?.summary} />
      <MidiStudio projectId={project && ID.test(project) ? project : undefined} />
    </>
  );
}
