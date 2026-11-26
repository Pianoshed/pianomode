/**
 * What a saved audio analysis remembers. The audio itself is NOT stored (it is large and belongs
 * to the person): only the settings, their corrections, and a short summary for the list.
 * To carry on, the person opens the same recording again and these settings are put back on it.
 *
 * Saved data is untrusted when it comes back; anything invalid is replaced by the normal default.
 */

import type { Correction } from "@/lib/audio/api";
import { type ChordSet, DEFAULT_DECODE, type DecodeOptions } from "@/lib/audio/chords";
import { AMBIGUITY_LEVELS, type AmbiguityLevel } from "@/lib/audio/studio";
import type { KeyChoice } from "@/lib/library/midiProject";

export const AUDIO_PROJECT_VERSION = 1;
const MAX_CORRECTIONS = 500;
/** Corrections are tied to exact times; if the new recording is this much longer or shorter, they are not applied. */
export const DURATION_TOLERANCE_SECONDS = 1.5;

export type AudioProjectSettings = {
  decode: DecodeOptions;
  keyChoice: KeyChoice | null;
  prefer: "sharps" | "flats";
  ambiguity: AmbiguityLevel;
  corrections: Correction[];
  fileName: string | null;
  duration: number | null;
  summary: { chords: number; key: string | null } | null;
};

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const num = (x: unknown, min: number, max: number): x is number => typeof x === "number" && Number.isFinite(x) && x >= min && x <= max;
const idx = (x: unknown): x is number => typeof x === "number" && Number.isInteger(x) && x >= 0 && x < 100_000;
const label = (x: unknown): x is string => typeof x === "string" && x.length > 0 && x.length <= 24;

function readCorrection(c: unknown): Correction | null {
  if (!isObj(c)) return null;
  if (c.op === "relabel" && idx(c.index) && label(c.label)) return { op: "relabel", index: c.index, label: c.label };
  if (c.op === "retime" && idx(c.index) && num(c.start, 0, 86_400) && num(c.end, 0, 86_400) && c.end > c.start) return { op: "retime", index: c.index, start: c.start, end: c.end };
  if (c.op === "add" && num(c.start, 0, 86_400) && num(c.end, 0, 86_400) && c.end > c.start && label(c.label)) return { op: "add", start: c.start, end: c.end, label: c.label };
  if (c.op === "delete" && idx(c.index)) return { op: "delete", index: c.index };
  return null;
}

export function serializeAudioProject(s: {
  decode: DecodeOptions;
  keyChoice: KeyChoice | null;
  prefer: "sharps" | "flats";
  ambiguity: AmbiguityLevel;
  corrections: readonly Correction[];
  fileName: string | null;
  duration: number | null;
  summary: { chords: number; key: string | null } | null;
}): Record<string, unknown> {
  return { v: AUDIO_PROJECT_VERSION, ...s };
}

/** Settings from whatever was saved. Never throws. */
export function restoreAudioProject(saved: unknown): AudioProjectSettings {
  const d = isObj(saved) ? saved : {};
  const dec = isObj(d.decode) ? d.decode : {};
  const decode: DecodeOptions = {
    set: (dec.set === "triads" || dec.set === "sevenths" ? dec.set : DEFAULT_DECODE.set) as ChordSet,
    stability: num(dec.stability, 0, 1) ? dec.stability : DEFAULT_DECODE.stability,
    minDuration: num(dec.minDuration, 0, 10) ? dec.minDuration : DEFAULT_DECODE.minDuration,
  };
  const kc = d.keyChoice;
  const corrections: Correction[] = [];
  if (Array.isArray(d.corrections)) {
    for (const c of d.corrections.slice(0, MAX_CORRECTIONS)) {
      const ok = readCorrection(c);
      if (ok) corrections.push(ok);
    }
  }
  const sum = d.summary;
  return {
    decode,
    keyChoice: isObj(kc) && typeof kc.tonic === "string" && /^[A-G][b#]?$/.test(kc.tonic) && (kc.mode === "major" || kc.mode === "minor") ? { tonic: kc.tonic, mode: kc.mode } : null,
    prefer: d.prefer === "flats" ? "flats" : "sharps",
    ambiguity: typeof d.ambiguity === "string" && d.ambiguity in AMBIGUITY_LEVELS ? (d.ambiguity as AmbiguityLevel) : "normal",
    corrections,
    fileName: typeof d.fileName === "string" ? d.fileName.slice(0, 200) : null,
    duration: num(d.duration, 0, 86_400) ? d.duration : null,
    summary: isObj(sum) && num(sum.chords, 0, 100_000) ? { chords: Math.round(sum.chords), key: typeof sum.key === "string" ? sum.key.slice(0, 40) : null } : null,
  };
}

/** Whether saved corrections still make sense on a recording of this length. */
export function sameRecording(saved: AudioProjectSettings, duration: number): boolean {
  return saved.duration === null || Math.abs(saved.duration - duration) <= DURATION_TOLERANCE_SECONDS;
}
