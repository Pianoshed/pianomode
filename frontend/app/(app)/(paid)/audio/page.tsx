import type { Metadata } from "next";
import { AudioAnalyzer } from "@/components/audio/AudioAnalyzer";
import { PageHeader } from "@/components/PageHeader";
import { findNavItem } from "@/lib/nav";

export const metadata: Metadata = { title: "Audio Analyzer" };

const ID = /^[0-9a-f-]{36}$/i;

export default async function AudioPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const item = findNavItem("audio");
  const { project } = await searchParams;
  return (
    <>
      <PageHeader title={item?.label ?? "Audio Analyzer"} description={item?.summary} />
      <AudioAnalyzer projectId={project && ID.test(project) ? project : undefined} />
    </>
  );
}
