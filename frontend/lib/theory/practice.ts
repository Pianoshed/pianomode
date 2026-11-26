/** Pure logic for the practice screen: what to send for each answer format, how topics are
 *  grouped, and how progress is described. No React, no network. */

import type { Overlay } from "@/lib/piano/highlight";
import type { Answer, AnswerFormat, Exercise, ExerciseKind, GradeStatus, KindProgress } from "./exercisesApi";

export type Draft = { text: string; choice: string | null; keys: ReadonlySet<number> };
export const EMPTY_DRAFT: Draft = { text: "", choice: null, keys: new Set() };

/** Split a typed list ("C E G", "C, E, G") into items. */
export const splitList = (text: string): string[] => text.split(/[\s,]+/).filter(Boolean);

/** The payload for the learner's draft, or null if nothing has been answered yet. A set of notes
 *  can be given as pressed keys (exact pitches) or as typed names; pressed keys win. */
export function answerFor(format: AnswerFormat, d: Draft): Answer | null {
  switch (format) {
    case "choice":
      return d.choice;
    case "text":
      return d.text.trim() ? d.text.trim() : null;
    case "note_names":
    case "chord_symbols": {
      const items = splitList(d.text);
      return items.length ? items : null;
    }
    case "note_set": {
      if (d.keys.size) return [...d.keys].sort((a, b) => a - b);
      const items = splitList(d.text);
      return items.length ? items : null;
    }
  }
}

/** Keys that show the question's notes. They are never labelled: a label could give the answer. */
export function overlayForExercise(ex: Exercise | null, picked: ReadonlySet<number>): Overlay | null {
  if (!ex) return null;
  const marks = new Map<number, { role: "tone" | "root"; label: string }>();
  for (const m of ex.show) marks.set(m, { role: "tone", label: "" });
  for (const m of picked) marks.set(m, { role: "root", label: "" });
  if (marks.size === 0) return null;
  return { source: "chord", title: "Exercise", marks, spelling: {} };
}

export const toggleKey = (keys: ReadonlySet<number>, midi: number): Set<number> => {
  const next = new Set(keys);
  if (next.has(midi)) next.delete(midi);
  else next.add(midi);
  return next;
};

/** "seventh_chords" -> "Seventh chords". Topics arrive as identifiers from the server. */
export function topicLabel(topic: string): string {
  const words = topic.replace(/_/g, " ").trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : topic;
}

export type TopicGroup = { topic: string; kinds: ExerciseKind[] };
/** Kinds grouped by topic, in the order the server lists them. */
export function groupByTopic(kinds: readonly ExerciseKind[]): TopicGroup[] {
  const groups: TopicGroup[] = [];
  for (const k of kinds) {
    const g = groups.find((x) => x.topic === k.topic);
    if (g) g.kinds.push(k);
    else groups.push({ topic: k.topic, kinds: [k] });
  }
  return groups;
}

export type ProgressText = { summary: string; recent: string | null };
/** Plain counts, no judgement words such as "mastered". */
export function describeProgress(p: Pick<KindProgress, "attempts" | "correct" | "recent_attempts" | "recent_correct"> | undefined): ProgressText {
  if (!p || p.attempts === 0) return { summary: "Not tried yet", recent: null };
  return {
    summary: `${p.correct} of ${p.attempts} correct`,
    recent: p.attempts > p.recent_attempts ? `${p.recent_correct} of your last ${p.recent_attempts}` : null,
  };
}

/** Progress for one kind at one difficulty. */
export const progressFor = (rows: readonly KindProgress[], kind: string, difficulty: string): KindProgress | undefined =>
  rows.find((r) => r.kind === kind && r.difficulty === difficulty);

/** Prerequisite kinds the learner has not attempted at any level, by title. Soft advice only. */
export function untriedPrerequisites(kind: ExerciseKind, all: readonly ExerciseKind[], rows: readonly KindProgress[]): string[] {
  const tried = new Set(rows.filter((r) => r.attempts > 0).map((r) => r.kind));
  return kind.prerequisites
    .filter((p) => !tried.has(p))
    .map((p) => all.find((k) => k.kind === p)?.title ?? p);
}

export const STATUS_TEXT: Record<GradeStatus, { title: string; tone: "success" | "info" | "error" }> = {
  correct: { title: "Correct", tone: "success" },
  enharmonic: { title: "Right notes, different spelling", tone: "info" },
  partial: { title: "Nearly", tone: "info" },
  incorrect: { title: "Not quite", tone: "error" },
  unreadable: { title: "That could not be read", tone: "error" },
};
