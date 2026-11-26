/** Typed call to the MIDI analysis endpoint. The server turns note events into chord segments,
 *  a key estimate and Roman numerals; the browser never does that itself. */

import { type ApiResult, api } from "@/lib/api";
import type { Candidate } from "@/lib/piano/theoryApi";

export type Hand = "L" | "R";
export type Grid = "beat" | "half_bar" | "bar";
export type Prefer = "sharps" | "flats";
export type TrackHandTag = "L" | "R" | "both" | "other";

export type MidiEventIn = { tick: number; kind: "note_on" | "note_off"; note: number; velocity: number; channel: number; track: number };
export type TrackStateIn = { track: number; name?: string | null; hand?: TrackHandTag | null; muted: boolean; solo: boolean };
export type KeyOut = { tonic: string; mode: string; name: string; signature: string; fifths: number; relative: string; parallel: string };
export type AnalyzeRequest = {
  ppq: number;
  events: MidiEventIn[];
  tempo_changes: { tick: number; bpm: number }[];
  time_signatures: { tick: number; numerator: number; denominator: number }[];
  key?: { tonic: string; mode: string } | null;
  grid: Grid;
  prefer: Prefer;
  track_states: TrackStateIn[];
  max_candidates: number;
  include_notes: boolean;
};

export type Numeral = {
  symbol: string;
  figure: string;
  degree: number;
  category: string;
  function: string | null;
  applied_to: string | null;
  borrowed_from: string | null;
  inversion: number | null;
  note: string | null;
  alternatives: string[];
};
export type SegmentStatus = "identified" | "ambiguous" | "no_reliable_label" | "silence";
export type Segment = {
  origin: "midi";
  start_beat: number;
  end_beat: number;
  start_sec: number;
  end_sec: number;
  status: SegmentStatus;
  reason: string | null;
  bass: string | null;
  pitches: number[];
  candidates: Candidate[];
  numeral: Numeral | null;
  warnings: string[];
};
export type NoteOut = {
  id: number;
  midi: number;
  name: string;
  velocity: number;
  track: number;
  channel: number;
  start_beat: number;
  end_beat: number;
  start_sec: number;
  end_sec: number;
  duration_beats: number;
  hand: Hand | null;
  hand_source: "auto" | "user" | null;
};
export type KeyEstimate = {
  candidates: { key: KeyOut; score: number }[];
  reliable: boolean;
  ambiguous: boolean;
  warnings: string[];
  method: string;
  score_meaning: string;
};
export type AnalyzeResponse = {
  segments: Segment[];
  key: KeyOut | null;
  key_source: "provided" | "estimated" | null;
  key_estimate: KeyEstimate;
  note_count: number;
  duration_beats: number;
  notes: NoteOut[] | null;
  warnings: string[];
  hand_note: string;
};

export const analyzeMidi = (body: AnalyzeRequest): Promise<ApiResult<AnalyzeResponse>> =>
  api<AnalyzeResponse>("/api/v1/theory/midi/analyze", { method: "POST", body });
