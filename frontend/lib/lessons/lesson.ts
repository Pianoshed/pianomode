/** Pure helpers for lessons: wording, ordering, and how an example is shown and played. */

import type { ScheduledEvent } from "@/lib/piano/audio";
import { type Mark, type Overlay, nameToPc } from "@/lib/piano/highlight";
import type { Example, ExampleItem, Goal, Level, LessonStatus, LessonSummary } from "./api";

export const LEVEL_LABEL: Record<Level, string> = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced", expert: "Expert" };
export const LEVEL_ORDER: readonly Level[] = ["beginner", "intermediate", "advanced", "expert"];
export const STATUS_LABEL: Record<LessonStatus, string> = { not_started: "Not started", in_progress: "In progress", practised: "Practised" };

/** "3 of 5", never showing more than the goal. */
export const goalText = (g: Pick<Goal, "correct" | "goal">): string => `${Math.min(g.correct, g.goal)} of ${g.goal}`;

/** Where a practice goal is practised: the theory screen opened on that exercise and level. */
export const practiceHref = (g: Pick<Goal, "kind" | "difficulty">): string =>
  `/theory?kind=${encodeURIComponent(g.kind)}&level=${encodeURIComponent(g.difficulty)}`;

export type LevelGroup = { level: Level; lessons: LessonSummary[] };
/** Lessons grouped by level, keeping curriculum order inside each group and omitting empty levels. */
export function groupByLevel(items: readonly LessonSummary[]): LevelGroup[] {
  return LEVEL_ORDER.map((level) => ({ level, lessons: items.filter((i) => i.level === level) })).filter((g) => g.lessons.length > 0);
}

/** The lesson to suggest next: the first unfinished one whose prerequisites are practised; failing
 *  that, the first unfinished one. Null when everything is practised. Advice only. */
export function suggestNext(items: readonly LessonSummary[]): LessonSummary | null {
  const open = items.filter((i) => i.status !== "practised");
  return open.find((i) => i.unmet_prerequisites.length === 0) ?? open[0] ?? null;
}

export function summaryCounts(items: readonly LessonSummary[]): { practised: number; total: number } {
  return { practised: items.filter((i) => i.status === "practised").length, total: items.length };
}

// ------------------------------------------------------------------ examples on the keyboard

const rootPc = (label: string): number | null => {
  const m = /^[A-G][#b]*/.exec(label);
  return m ? nameToPc(m[0]) : null;
};

/** Marks for one item of an example. Chords mark their root; a scale marks the tonic. Keys are
 *  labelled with their spelled names (a lesson teaches the names; an exercise would not). */
export function overlayForItem(example: Pick<Example, "type" | "items">, index: number): Overlay | null {
  const item: ExampleItem | undefined = example.items[index];
  if (!item || item.midi.length === 0) return null;
  const root = example.type === "scale" ? nameToPc(example.items[0]?.notes[0] ?? "") : example.type === "interval" ? null : rootPc(item.label);
  const marks = new Map<number, Mark>();
  const spelling: Record<number, string> = {};
  item.midi.forEach((m, i) => {
    const name = item.notes[i] ?? "";
    const pc = ((m % 12) + 12) % 12;
    marks.set(m, { role: root !== null && pc === root ? "root" : "tone", label: name });
    if (name && spelling[pc] === undefined) spelling[pc] = name;
  });
  return { source: "chord", title: item.label, marks, spelling };
}

/** The example's playback in the form the audio engine takes. */
export const eventsFor = (example: Pick<Example, "play">): ScheduledEvent[] =>
  example.play.map((p) => ({ notes: p.notes, start: p.start, duration: p.duration }));

/** Which item is sounding at `beat` (the last step that has started). */
export function itemAtBeat(example: Pick<Example, "play">, beat: number): number {
  let item = example.play[0]?.item ?? 0;
  for (const p of example.play) if (p.start <= beat + 1e-6) item = p.item;
  return item;
}

export const exampleBeats = (example: Pick<Example, "play">): number => example.play.reduce((m, p) => Math.max(m, p.start + p.duration), 0);

/** MIDI note to centre the keyboard on for an item. */
export function centreOfItem(item: Pick<ExampleItem, "midi">): number | null {
  return item.midi.length ? Math.round((Math.min(...item.midi) + Math.max(...item.midi)) / 2) : null;
}
