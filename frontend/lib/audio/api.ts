/** Typed call to the audio interpretation endpoint. The browser estimates chords from the sound;
 *  the server turns those estimates into hypotheses (symbol, alternatives, ambiguity, key,
 *  Roman numerals) and applies a person's corrections. No confidence is ever invented: the
 *  server returns `confidence: null` unless a named calibration is supplied, and none is. */

import { type ApiResult, api } from "@/lib/api";
import type { KeyEstimate, KeyOut, Numeral, Prefer } from "@/lib/midi/api";
import type { AudioRegion } from "./chords";

export type Correction =
  | { op: "relabel"; index: number; label: string }
  | { op: "retime"; index: number; start: number; end: number }
  | { op: "add"; start: number; end: number; label: string }
  | { op: "delete"; index: number };

export type HypothesisStatus = "estimated" | "ambiguous" | "no_chord" | "unrecognised_label" | "user_set";
export type Alternative = { label: string | null; symbol: string | null; source: "model" | "pitch_evidence"; model_score: number | null };
export type Hypothesis = {
  origin: "audio" | "user";
  start: number;
  end: number;
  status: HypothesisStatus;
  symbol: string | null;
  raw_label: string;
  alternatives: Alternative[];
  model_score: number | null;
  confidence: number | null;
  calibration: string | null;
  bass: string | null;
  pitch_classes: number[] | null;
  numeral: Numeral | null;
  warnings: string[];
};
export type AppliedCorrection = { kind: string; index: number; before: Hypothesis | null; after: Hypothesis | null };
export type InterpretRequest = {
  regions: AudioRegion[];
  key?: { tonic: string; mode: string } | null;
  min_duration: number;
  score_margin: number;
  prefer: Prefer;
  corrections: Correction[];
};
export type InterpretResponse = {
  hypotheses: Hypothesis[];
  original: Hypothesis[] | null;
  corrections: AppliedCorrection[];
  key: KeyOut | null;
  key_source: "provided" | "estimated" | null;
  key_estimate: KeyEstimate | null;
  warnings: string[];
  evidence_note: string;
};

export const interpretAudio = (body: InterpretRequest): Promise<ApiResult<InterpretResponse>> =>
  api<InterpretResponse>("/api/v1/theory/audio/interpret", { method: "POST", body });
