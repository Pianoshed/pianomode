/** Typed calls to the practice API: scoring, saved results and progress. */

import { type ApiResult, api } from "@/lib/api";
import type { Level } from "@/lib/movements/api";

export type Hands = "both" | "L" | "R";
export type Played = { midi: number; time_s: number; off_time_s?: number };

export type ScoreBody = {
  movement: { slug: string; level: Level; key?: string; hands: Hands };
  played: Played[];
  tempo_bpm: number;
  window_ms: number;
  offset_s: number;
  latency_ms: number;
  octave_equivalent: boolean;
  beat_range?: [number, number];
  save?: { session_id: string; pass_index: number };
};

export type NoteResult = { index: number; midi: number; name: string; start_beat: number; hand: string | null; chord_index: number | null; status: "on_time" | "early" | "late" | "missed" | "near_miss"; error_ms: number | null; played_midi: number | null; held_ratio: number | null };
export type Score = {
  expected: number; hits: number; on_time: number; early: number; late: number; missed: number; near_miss: number; extra: number; short_holds: number; accuracy: number;
  timing: { hits: number; mean_error_ms: number | null; mean_abs_error_ms: number | null; median_error_ms: number | null; spread_ms: number | null; tendency: "rushing" | "dragging" | "steady" | "not_enough_notes" };
  notes: NoteResult[];
  extras: { midi: number; name: string; time_s: number; beat: number }[];
  chords: { chord_index: number; expected: number; hit: number; complete: boolean; spread_ms: number | null }[];
  hands: { hand: "L" | "R"; expected: number; hit: number; accuracy: number }[];
  feedback: string[]; window_ms: number; tempo_bpm: number; limits: string[]; source: string; saved_id: string | null;
};

export const WINDOW_BY_LEVEL: Record<Level, number> = { beginner: 250, intermediate: 150, advanced: 90, expert: 60 };

export const scorePass = (body: ScoreBody): Promise<ApiResult<Score>> => api("/api/v1/practice/score", { method: "POST", body });

export type Attempt = {
  id: string; session_id: string; created_at: string; movement_slug: string; level: Level; key: string | null; mode: "play" | "wait"; hands: Hands; pass_index: number;
  tempo_bpm: number | null; window_ms: number | null; expected: number; hits: number; accuracy: number; on_time: number; early: number; late: number; missed: number; near_miss: number; extra: number;
  mean_error_ms: number | null; tendency: string | null;
};
export type Progress = { movement_slug: string; level: Level; mode: "play" | "wait"; attempts: number; best_accuracy: number; last_accuracy: number; best_tempo_at_90: number | null; last_practised: string };
export type History = { items: Attempt[]; progress: Progress[]; total: number };

export const saveWaitResult = (body: { movement_slug: string; level: Level; key?: string; hands: Hands; session_id: string; steps: number; first_try: number; wrong_presses: number }): Promise<ApiResult<Attempt>> =>
  api("/api/v1/practice/wait-results", { method: "POST", body });
export const getHistory = (movement?: string): Promise<ApiResult<History>> => api(`/api/v1/practice/history${movement ? `?movement=${encodeURIComponent(movement)}` : ""}`);
export const deleteAttempt = (id: string): Promise<ApiResult<null>> => api(`/api/v1/practice/attempts/${id}`, { method: "DELETE" });
export const deleteHistory = (): Promise<ApiResult<{ deleted: number }>> => api("/api/v1/practice/history", { method: "DELETE" });
