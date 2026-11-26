/** Synthesised audio with a known right answer: used by tests and by the built-in example. Each note is a sum of
 *  harmonics with amplitude 1/h, which is closer to a real instrument than a pure sine. */

import { SAMPLE_RATE } from "./chroma";

export type Voice = { midi: number; amp?: number };
export type Segment = { notes: number[]; seconds: number; bass?: number };

export const hz = (midi: number, cents = 0): number => 440 * 2 ** ((midi - 69 + cents / 100) / 12);

/** Add notes to `out` from `startSample` for `length` samples. */
export function addNotes(out: Float32Array, startSample: number, length: number, notes: readonly number[], opts: { amp?: number; partials?: number; cents?: number; sampleRate?: number } = {}): void {
  const sr = opts.sampleRate ?? SAMPLE_RATE;
  const amp = opts.amp ?? 0.2;
  const partials = opts.partials ?? 6;
  const fade = Math.min(Math.floor(0.01 * sr), Math.floor(length / 4));
  for (const midi of notes) {
    const f0 = hz(midi, opts.cents ?? 0);
    for (let h = 1; h <= partials; h++) {
      const f = f0 * h;
      if (f > sr / 2 - 100) break;
      const w = (2 * Math.PI * f) / sr;
      const a = amp / h;
      for (let i = 0; i < length; i++) {
        const env = i < fade ? i / fade : i > length - fade ? (length - i) / fade : 1;
        out[startSample + i] = (out[startSample + i] as number) + a * env * Math.sin(w * i);
      }
    }
  }
}

/** A progression: each segment sounds its notes (plus an optional bass note two octaves down). */
export function synthProgression(segments: readonly Segment[], opts: { cents?: number; amp?: number; sampleRate?: number } = {}): Float32Array {
  const sr = opts.sampleRate ?? SAMPLE_RATE;
  const total = segments.reduce((n, s) => n + Math.round(s.seconds * sr), 0);
  const out = new Float32Array(total);
  let at = 0;
  for (const s of segments) {
    const len = Math.round(s.seconds * sr);
    addNotes(out, at, len, s.notes, { ...opts, amp: opts.amp ?? 0.18 });
    if (s.bass !== undefined) addNotes(out, at, len, [s.bass], { ...opts, amp: (opts.amp ?? 0.18) * 1.3, partials: 4 });
    at += len;
  }
  return out;
}

/** A chord as notes: root position triad/seventh in the octave from middle C, root in the bass. */
export function voicing(rootPc: number, intervals: readonly number[]): { notes: number[]; bass: number } {
  const base = 60 + rootPc;
  return { notes: intervals.map((i) => base + i), bass: 36 + rootPc };
}

export const QUALITY_INTERVALS: Record<string, number[]> = {
  maj: [0, 4, 7],
  min: [0, 3, 7],
  "7": [0, 4, 7, 10],
  maj7: [0, 4, 7, 11],
  min7: [0, 3, 7, 10],
};

/** Deterministic white-ish noise (so tests do not depend on Math.random). */
export function noise(length: number, amp: number, seed = 1): Float32Array {
  let s = seed >>> 0;
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    out[i] = ((s / 0xffffffff) * 2 - 1) * amp;
  }
  return out;
}
