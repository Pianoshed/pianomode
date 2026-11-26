/** Typed calls to the chord-movement API. All musical content (chords, voicings, numerals,
 *  substitutions) comes from the server; the browser only displays and plays it. The types are
 *  checked against a real response in `__fixtures__` (regenerate with the backend export script). */

import { type ApiResult, api } from "@/lib/api";

export type Level = "beginner" | "intermediate" | "advanced" | "expert";
export const LEVELS: readonly Level[] = ["beginner", "intermediate", "advanced", "expert"];
export const LEVEL_INFO: Record<Level, { label: string; blurb: string }> = {
  beginner: { label: "Beginner", blurb: "Triads, root position" },
  intermediate: { label: "Intermediate", blurb: "Seventh chords, inversions" },
  advanced: { label: "Advanced", blurb: "Smooth voice leading, rootless" },
  expert: { label: "Expert", blurb: "Extensions and substitutions" },
};

export type Status = "draft" | "under_review" | "approved" | "published" | "archived";
export type Hand = "L" | "R";

export type Step = {
  index: number;
  symbol: string;
  roman: string | null;
  beat: number;
  duration: number;
  role: string;
  chord_tones: string[];
  bass: string;
  inversion: string;
  left: number[];
  right: number[];
  left_names: string[];
  right_names: string[];
  voicing_type: string;
  omitted: string[];
  tensions: string[];
  explanation: string[];
  cost: number;
};
export type PlaybackEvent = {
  midi: number;
  hand: Hand;
  start_beat: number;
  duration_beats: number;
  chord_index: number;
  velocity: number;
};
export type Version = {
  level: Level;
  voicing_type: string;
  theory_explanation: string;
  practice: string;
  variations: string[];
  total_cost: number;
  method: string;
  warnings: string[];
  validation_errors: string[];
  validation_warnings: string[];
  tempo: number | null;
  time_signature: number[];
  total_beats: number;
  steps: Step[];
  playback: PlaybackEvent[];
};
export type Built = {
  schema_version: number;
  generator_version: number;
  slug: string;
  name: string;
  key: { tonic: string; mode: string };
  tempo: number;
  time_signature: number[];
  tags: string[];
  author: string | null;
  source: string | null;
  template_id: string | null;
  transposition_options: string[];
  versions: Version[];
};
export type MovementDetail = { movement: Built; live: boolean; score_meaning: string };

export type MovementSummary = {
  slug: string;
  name: string;
  key: string;
  mode: string;
  tags: string[];
  levels: Level[];
  chords: string[];
  romans: (string | null)[];
  tempo: number;
  time_signature: number[];
  author: string | null;
  published_at: string | null;
};
export type MovementList = { items: MovementSummary[]; total: number };

export type ListFilters = { q?: string; level?: Level | ""; mode?: "major" | "minor" | ""; tag?: string };

export function listMovements(filters: ListFilters): Promise<ApiResult<MovementList>> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v);
  const qs = params.toString();
  return api<MovementList>(`/api/v1/movements${qs ? `?${qs}` : ""}`);
}

export function getMovement(slug: string, key?: string): Promise<ApiResult<MovementDetail>> {
  const qs = key ? `?key=${encodeURIComponent(key)}` : "";
  return api<MovementDetail>(`/api/v1/movements/${encodeURIComponent(slug)}${qs}`);
}

// content admin ------------------------------------------------------------------------------

export type HistoryEntry = {
  revision: number;
  at: string;
  by: string;
  action: string;
  note: string;
  from_status: string | null;
  to_status: string | null;
};
export type AdminSummary = {
  id: string;
  slug: string;
  name: string;
  status: Status;
  revision: number;
  mode: string;
  tags: string[];
  updated_at: string;
};
export type AdminMovement = AdminSummary & {
  definition: Record<string, unknown>;
  history: HistoryEntry[];
  allowed_transitions: Status[];
  published_at: string | null;
};
export type ValidationReport = { publishable: boolean; blockers: string[]; warnings: string[]; can_publish_now: boolean };

const ADMIN = "/api/v1/admin/movements";

export function adminList(status?: Status | "", q?: string): Promise<ApiResult<{ items: AdminSummary[]; total: number }>> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (q) params.set("q", q);
  const qs = params.toString();
  return api(`${ADMIN}${qs ? `?${qs}` : ""}`);
}
export const adminGet = (id: string): Promise<ApiResult<AdminMovement>> => api(`${ADMIN}/${id}`);
export const adminValidate = (id: string): Promise<ApiResult<ValidationReport>> => api(`${ADMIN}/${id}/validate`, { method: "POST" });
export const adminSetStatus = (id: string, to: Status, note = ""): Promise<ApiResult<AdminMovement>> =>
  api(`${ADMIN}/${id}/status`, { method: "POST", body: { to, note } });
export const adminPreview = (id: string): Promise<ApiResult<{ movement: Built; validation: ValidationReport }>> => api(`${ADMIN}/${id}/preview`);
export const adminCreate = (body: Record<string, unknown>): Promise<ApiResult<AdminMovement>> => api(ADMIN, { method: "POST", body });
export const adminUpdate = (id: string, body: Record<string, unknown>): Promise<ApiResult<AdminMovement>> =>
  api(`${ADMIN}/${id}`, { method: "PUT", body });

/** What a status change is called on a button. */
export const TRANSITION_LABEL: Record<Status, string> = {
  draft: "Return to draft",
  under_review: "Submit for review",
  approved: "Approve",
  published: "Publish",
  archived: "Archive",
};
/** Moves that are not simply "go to the target": unpublishing and restoring have their own names. */
export function transitionLabel(from: Status, to: Status): string {
  if (from === "published" && to === "approved") return "Unpublish";
  if (from === "archived" && to === "draft") return "Restore";
  if (from === "under_review" && to === "draft") return "Request changes";
  return TRANSITION_LABEL[to];
}
