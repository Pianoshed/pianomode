import type { Metadata } from "next";
import { LessonView } from "@/components/lessons/LessonView";

type Props = { params: Promise<{ id: string }> };

export const metadata: Metadata = { title: "Lesson" };

export default async function LessonPage({ params }: Props) {
  const { id } = await params;
  return <LessonView id={id} />;
}
