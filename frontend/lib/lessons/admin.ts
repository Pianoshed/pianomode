/** Typed calls and form helpers for writing lessons (educators and admins; the server enforces
 *  it). A lesson is text plus example *specifications*; the engine builds every note, so the form
 *  never asks an author to type notes for an example, only a chord symbol, a scale name, etc. */

import { type ApiResult, api } from "@/lib/api";
import type { ExampleType, LessonDetail, Level } from "@/lib/lessons/api";

export type AdminStatus = "draft" | "under_review" | "approved" | "published" | "archived";
export const LEVEL_OPTIONS: Level[] = ["beginner", "intermediate", "advanced", "expert"];

export type ExampleDef = { type: ExampleType; caption: string } & Record<string, unknown>;
export type LessonDef = {
  id: string;
  title: string;
  level: Level;
  summary: string;
  objectives: string[];
  prerequisites: string[];
  sections: { heading: string; body: string[]; examples: ExampleDef[] }[];
  practice: { kind: string; difficulty: Level; goal: number }[];
  movement_template: string | null;
  tags: string[];
};
export type AdminLesson = {
  id: string;
  lesson_id: string;
  title: string;
  level: Level;
  status: AdminStatus;
  revision: number;
  definition: Partial<LessonDef>;
  history: { revision: number; at: string; actor: string; action: string; note: string }[];
  allowed_transitions: AdminStatus[];
  published_at: string | null;
  updated_at: string;
};
export type AdminLessonSummary = { id: string; lesson_id: string; title: string; level: Level; status: AdminStatus; revision: number; updated_at: string };
export type LessonPreview = { lesson: LessonDetail; publishable: boolean; blockers: string[]; warnings: string[]; can_publish_now: boolean };

const ADMIN = "/api/v1/admin/lessons";
export const listAdminLessons = (): Promise<ApiResult<{ items: AdminLessonSummary[]; total: number }>> => api(ADMIN);
export const getAdminLesson = (id: string): Promise<ApiResult<AdminLesson>> => api(`${ADMIN}/${id}`);
export const createLesson = (body: LessonDef): Promise<ApiResult<AdminLesson>> => api(ADMIN, { method: "POST", body });
export const updateLesson = (id: string, body: LessonDef & { revision: number }): Promise<ApiResult<AdminLesson>> => api(`${ADMIN}/${id}`, { method: "PUT", body });
export const previewLessonDraft = (body: LessonDef): Promise<ApiResult<LessonPreview>> => api(`${ADMIN}/preview`, { method: "POST", body });
export const previewStoredLesson = (id: string): Promise<ApiResult<LessonPreview>> => api(`${ADMIN}/${id}/preview`);
export const setLessonStatus = (id: string, to: AdminStatus, note = ""): Promise<ApiResult<AdminLesson>> =>
  api(`${ADMIN}/${id}/status`, { method: "POST", body: { to, note } });

const LABEL: Record<string, string> = {
  "draft>under_review": "Submit for review",
  "under_review>draft": "Request changes",
  "under_review>approved": "Approve",
  "approved>draft": "Return to draft",
  "approved>published": "Publish",
  "published>approved": "Unpublish",
  "archived>draft": "Restore",
};
export const lessonTransitionLabel = (from: AdminStatus, to: AdminStatus): string => (to === "archived" ? "Archive" : (LABEL[`${from}>${to}`] ?? to));

// ---- form model: everything is text while editing, and parsed once on save ----

/** The fields each example type needs, with a hint. The engine validates the values. */
export const EXAMPLE_FIELDS: Record<ExampleType, { key: string; label: string; hint: string }[]> = {
  chord: [
    { key: "symbol", label: "Chord", hint: "Cmaj7" },
    { key: "octave", label: "Octave (1-6)", hint: "4" },
  ],
  scale: [
    { key: "root", label: "Starting note", hint: "C" },
    { key: "scale", label: "Scale id", hint: "major" },
    { key: "octave", label: "Octave (1-6)", hint: "4" },
  ],
  interval: [
    { key: "lower", label: "Lower note", hint: "C4" },
    { key: "upper", label: "Upper note", hint: "G4" },
  ],
  sequence: [
    { key: "chords", label: "Chords (space separated)", hint: "Dm7 G7 Cmaj7" },
    { key: "key", label: "Key for Roman numerals (optional)", hint: "C major" },
    { key: "octave", label: "Octave (1-6)", hint: "4" },
  ],
};

export type ExampleForm = { type: ExampleType; caption: string; fields: Record<string, string> };
export type LessonForm = {
  id: string; title: string; level: Level; summary: string; objectives: string; prerequisites: string; tags: string;
  movement_template: string;
  sections: { heading: string; body: string; examples: ExampleForm[] }[];
  practice: { kind: string; difficulty: Level; goal: string }[];
};

export const emptyExample = (type: ExampleType = "chord"): ExampleForm => ({ type, caption: "", fields: {} });
export const emptyForm = (): LessonForm => ({
  id: "", title: "", level: "beginner", summary: "", objectives: "", prerequisites: "", tags: "", movement_template: "",
  sections: [{ heading: "", body: "", examples: [] }],
  practice: [{ kind: "", difficulty: "beginner", goal: "3" }],
});

const lines = (text: string): string[] => text.split("\n").map((l) => l.trim()).filter(Boolean);
/** Paragraphs are separated by a blank line. */
export const paragraphs = (text: string): string[] => text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
export const words = (text: string): string[] => text.split(/[\s,;]+/).map((w) => w.trim()).filter(Boolean);

function exampleDef(e: ExampleForm): ExampleDef {
  const out: ExampleDef = { type: e.type, caption: e.caption.trim() };
  for (const { key } of EXAMPLE_FIELDS[e.type]) {
    const raw = (e.fields[key] ?? "").trim();
    if (!raw) continue;
    if (key === "chords") out[key] = words(raw);
    else if (key === "octave") out[key] = Number.isInteger(Number(raw)) ? Number(raw) : raw; // the engine rejects a non-number
    else out[key] = raw;
  }
  return out;
}

export function definitionFromForm(f: LessonForm): LessonDef {
  return {
    id: f.id.trim(),
    title: f.title.trim(),
    level: f.level,
    summary: f.summary.trim(),
    objectives: lines(f.objectives),
    prerequisites: words(f.prerequisites),
    sections: f.sections.map((s) => ({ heading: s.heading.trim(), body: paragraphs(s.body), examples: s.examples.map(exampleDef) })),
    practice: f.practice.map((p) => ({ kind: p.kind.trim(), difficulty: p.difficulty, goal: Number(p.goal) })),
    movement_template: f.movement_template.trim() || null,
    tags: words(f.tags),
  };
}

export function formFromDefinition(d: Partial<LessonDef>): LessonForm {
  const sections = (d.sections ?? []).map((s) => ({
    heading: s.heading,
    body: s.body.join("\n\n"),
    examples: (s.examples ?? []).map((e): ExampleForm => {
      const fields: Record<string, string> = {};
      for (const { key } of EXAMPLE_FIELDS[e.type]) {
        const v = e[key];
        if (v !== undefined && v !== null) fields[key] = Array.isArray(v) ? v.join(" ") : String(v);
      }
      return { type: e.type, caption: e.caption, fields };
    }),
  }));
  const practice = (d.practice ?? []).map((p) => ({ kind: p.kind, difficulty: p.difficulty, goal: String(p.goal) }));
  const blank = emptyForm();
  return {
    id: d.id ?? "",
    title: d.title ?? "",
    level: d.level ?? "beginner",
    summary: d.summary ?? "",
    objectives: (d.objectives ?? []).join("\n"),
    prerequisites: (d.prerequisites ?? []).join(" "),
    tags: (d.tags ?? []).join(" "),
    movement_template: d.movement_template ?? "",
    sections: sections.length ? sections : blank.sections,
    practice: practice.length ? practice : blank.practice,
  };
}
