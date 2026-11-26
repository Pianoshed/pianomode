/** Pure logic for the Audio Analyzer: requests, how a hypothesis is described, and how a person's
 *  corrections to chord regions are expressed. No React, no network, no clock. */

import type { Prefer } from "@/lib/midi/api";
import type { AudioRegion } from "./chords";
import type { Correction, Hypothesis, InterpretRequest } from "./api";

/** A region shorter than this cannot be made by a correction. */
export const MIN_REGION = 0.05;
export const MAX_LABEL = 40;

export type InterpretOptions = { key: { tonic: string; mode: string } | null; prefer: Prefer; minDuration: number; scoreMargin: number; corrections: readonly Correction[] };
/** How close another reading's score must be for a region to be called uncertain. This estimator's
 *  scores for clean synthetic chords lead the nearest rival by 0.037 or more, so 0.03 does not
 *  flag clean audio and flags anything closer. It is a measured starting point, not a calibration:
 *  real recordings are noisier and will be flagged more often, which is the intent. */
export const AMBIGUITY_LEVELS = { fewer: 0.015, normal: 0.03, more: 0.06 } as const;
export type AmbiguityLevel = keyof typeof AMBIGUITY_LEVELS;
export const DEFAULT_INTERPRET: InterpretOptions = { key: null, prefer: "sharps", minDuration: 0.25, scoreMargin: AMBIGUITY_LEVELS.normal, corrections: [] };

export function buildInterpretRequest(regions: readonly AudioRegion[], o: Partial<InterpretOptions> = {}): InterpretRequest {
  const opt = { ...DEFAULT_INTERPRET, ...o };
  return {
    regions: regions.map((r) => ({ ...r, bass_pc: r.bass_pc, pitch_classes: r.pitch_classes })),
    key: opt.key,
    min_duration: opt.minDuration,
    score_margin: opt.scoreMargin,
    prefer: opt.prefer,
    corrections: [...opt.corrections],
  };
}

// ------------------------------------------------------------------ describing a hypothesis

export type Look = { label: string; sublabel: string | null; kind: "estimated" | "ambiguous" | "none" | "unknown" | "user" };
/** What a timeline cell says. Uncertainty is kept visible: an ambiguous reading ends in a question
 *  mark, no chord says so, and a label the engine could not read shows "?". */
export function look(h: Hypothesis): Look {
  const numeral = h.numeral?.figure ?? null;
  switch (h.status) {
    case "no_chord":
      return { label: "no chord", sublabel: null, kind: "none" };
    case "unrecognised_label":
      return { label: "?", sublabel: null, kind: "unknown" };
    case "user_set":
      return { label: h.symbol ?? h.raw_label, sublabel: numeral, kind: "user" };
    case "ambiguous":
      return { label: `${h.symbol ?? h.raw_label}?`, sublabel: numeral, kind: "ambiguous" };
    default:
      return { label: h.symbol ?? h.raw_label, sublabel: numeral, kind: "estimated" };
  }
}

export const STATUS_TEXT: Record<Hypothesis["status"], string> = {
  estimated: "Estimated from the audio. One reading is clearly ahead.",
  ambiguous: "Estimated from the audio, but another reading is almost as likely. Check the alternatives.",
  no_chord: "No chord was heard here (silence, or sound without clear pitches).",
  unrecognised_label: "The estimate could not be turned into a chord this app understands.",
  user_set: "Set by you. It is not an estimate from the audio.",
};

export const hypothesisAt = (hyps: readonly Hypothesis[], t: number): number => hyps.findIndex((h) => h.start <= t && t < h.end);

/** The empty stretch around `t` (between regions), or null if `t` is inside a region. */
export function gapAround(hyps: readonly Hypothesis[], t: number, duration: number): { start: number; end: number } | null {
  if (hypothesisAt(hyps, t) >= 0) return null;
  const before = [...hyps].filter((h) => h.end <= t).sort((a, b) => b.end - a.end)[0];
  const after = [...hyps].filter((h) => h.start > t).sort((a, b) => a.start - b.start)[0];
  const start = before?.end ?? 0;
  const end = after?.start ?? duration;
  return end - start >= MIN_REGION ? { start, end } : null;
}

// ------------------------------------------------------------------ editing regions

export class EditError extends Error {}

export const cleanLabel = (text: string): string => {
  const t = text.trim();
  if (!t) throw new EditError("Type a chord, such as Am7 or C/E.");
  if (t.length > MAX_LABEL) throw new EditError(`A chord label can be at most ${MAX_LABEL} characters.`);
  return t;
};

const touches = (a: number, b: number): boolean => Math.abs(a - b) < 1e-3;
const near = (t: number): number => Math.round(t * 1000) / 1000;

/** Move the start or end of a region. If a neighbour shares that edge it moves too, so no gap or
 *  overlap is left. The server refuses a region that overlaps another, so the order matters: the
 *  region that is giving up time is shortened first. */
export function edgeEdits(hyps: readonly Hypothesis[], index: number, edge: "start" | "end", to: number, duration: number): Correction[] {
  const h = hyps[index];
  if (!h) throw new EditError("That chord no longer exists.");
  const t = near(to);
  if (!Number.isFinite(t) || t < 0 || t > duration) throw new EditError(`Choose a time between 0 and ${duration.toFixed(1)} seconds.`);
  const start = edge === "start" ? t : h.start;
  const end = edge === "end" ? t : h.end;
  if (end - start < MIN_REGION) throw new EditError("That would make the chord shorter than a twentieth of a second.");
  if (edge === "start") {
    const prev = hyps[index - 1];
    if (prev && touches(prev.end, h.start)) {
      if (t - prev.start < MIN_REGION) throw new EditError("That would squeeze the chord before it to nothing.");
      const mine: Correction = { op: "retime", index, start, end };
      const theirs: Correction = { op: "retime", index: index - 1, start: prev.start, end: t };
      return t > h.start ? [mine, theirs] : [theirs, mine];
    }
    if (prev && t < prev.end) throw new EditError("That would overlap the chord before it.");
    return [{ op: "retime", index, start, end }];
  }
  const next = hyps[index + 1];
  if (next && touches(next.start, h.end)) {
    if (next.end - t < MIN_REGION) throw new EditError("That would squeeze the chord after it to nothing.");
    const mine: Correction = { op: "retime", index, start, end };
    const theirs: Correction = { op: "retime", index: index + 1, start: t, end: next.end };
    return t > h.end ? [theirs, mine] : [mine, theirs];
  }
  if (next && t > next.start) throw new EditError("That would overlap the chord after it.");
  return [{ op: "retime", index, start, end }];
}

/** Cut a region in two at `t`; both halves keep the label and are marked as set by you. */
export function splitEdits(hyps: readonly Hypothesis[], index: number, t: number): Correction[] {
  const h = hyps[index];
  if (!h) throw new EditError("That chord no longer exists.");
  const at = near(t);
  if (at - h.start < MIN_REGION || h.end - at < MIN_REGION) throw new EditError("Move the playhead inside the chord, away from its ends, to split it.");
  return [{ op: "retime", index, start: h.start, end: at }, { op: "add", start: at, end: h.end, label: h.raw_label }];
}

/** Join a region with the one after it, keeping the first one's chord. */
export function mergeEdits(hyps: readonly Hypothesis[], index: number): Correction[] {
  const h = hyps[index];
  const next = hyps[index + 1];
  if (!h || !next) throw new EditError("There is no chord after this one to join.");
  if (!touches(h.end, next.start)) throw new EditError("There is a gap between these chords, so they cannot be joined.");
  return [{ op: "delete", index: index + 1 }, { op: "retime", index, start: h.start, end: next.end }];
}

export const relabelEdit = (index: number, label: string): Correction => ({ op: "relabel", index, label: cleanLabel(label) });
export const deleteEdit = (index: number): Correction => ({ op: "delete", index });
export function addEdit(gap: { start: number; end: number } | null, label: string): Correction {
  if (!gap) throw new EditError("Put the playhead in an empty stretch, between chords, to add one.");
  return { op: "add", start: gap.start, end: gap.end, label: cleanLabel(label) };
}

/** How many corrections a person has made, in words. */
export const correctionSummary = (n: number): string => (n === 0 ? "No corrections" : `${n} correction${n === 1 ? "" : "s"}`);

// ------------------------------------------------------------------ waveform

/** Largest absolute sample in each of `buckets` equal slices, for drawing an overview. */
export function waveformPeaks(samples: Float32Array, buckets: number): Float32Array {
  const out = new Float32Array(Math.max(0, buckets));
  if (samples.length === 0 || buckets <= 0) return out;
  const per = samples.length / buckets;
  for (let b = 0; b < buckets; b++) {
    const from = Math.floor(b * per);
    const to = Math.min(samples.length, Math.max(from + 1, Math.floor((b + 1) * per)));
    let peak = 0;
    for (let i = from; i < to; i++) {
      const v = Math.abs(samples[i] as number);
      if (v > peak) peak = v;
    }
    out[b] = peak;
  }
  return out;
}
