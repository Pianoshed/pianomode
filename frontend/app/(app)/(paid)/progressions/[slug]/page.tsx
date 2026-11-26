import type { Metadata } from "next";
import { MovementPlayer } from "@/components/movements/MovementPlayer";
import { PageHeader } from "@/components/PageHeader";
import { progressionFromQuery } from "@/lib/library/progression";

type Props = { params: Promise<{ slug: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export const metadata: Metadata = { title: "Chord movement" };

export default async function MovementPage({ params, searchParams }: Props) {
  const { slug } = await params;
  const initial = progressionFromQuery(await searchParams); // from a saved progression's link; ignored when absent
  return (
    <>
      <PageHeader title="Chord movement" description="Play it, compare the levels, and see every note on the keys." />
      <MovementPlayer slug={slug} initial={initial} />
    </>
  );
}
