/** Pure helpers for playing a movement and showing it on the keyboard. No React, no audio, no
 *  clock: the player component supplies those, so this logic can be unit-tested. */

import type { ScheduledEvent } from "@/lib/piano/audio";
import { type Mark, type Overlay, nameToPc } from "@/lib/piano/highlight";
import type { Hand, Step, Version } from "./api";

export type Hands = { L: boolean; R: boolean };
export const BOTH_HANDS: Hands = { L: true, R: true };
const EPS = 1e-6;

/** Index of the chord sounding at `beat`. Before the start it is the first chord; at or after the
 *  end it is the last, so the display never goes blank at a loop point. */
export function stepAtBeat(version: Pick<Version, "steps">, beat: number): number {
  const steps = version.steps;
  if (steps.length === 0) return -1;
  for (let i = steps.length - 1; i >= 0; i--) {
    if (beat + EPS >= (steps[i] as Step).beat) return i;
  }
  return 0;
}

/** Notes to schedule, starting from `fromBeat` (0 = from the top). Notes already finished are
 *  dropped; a note that is mid-way keeps only its remaining length. Muted hands are left out. */
export function eventsFrom(version: Pick<Version, "playback">, fromBeat: number, hands: Hands): ScheduledEvent[] {
  const groups = new Map<string, { notes: number[]; start: number; duration: number }>();
  for (const e of version.playback) {
    if (!hands[e.hand]) continue;
    const end = e.start_beat + e.duration_beats;
    if (end <= fromBeat + EPS) continue;
    const start = Math.max(0, e.start_beat - fromBeat);
    const duration = e.start_beat >= fromBeat ? e.duration_beats : end - fromBeat;
    const key = `${start}:${duration}`;
    const g = groups.get(key) ?? { notes: [], start, duration };
    g.notes.push(e.midi);
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => a.start - b.start);
}

/** Notes of one chord, for auditioning it by itself. */
export function stepEvent(step: Step, hands: Hands): ScheduledEvent[] {
  const notes = [...(hands.L ? step.left : []), ...(hands.R ? step.right : [])];
  return notes.length ? [{ notes, start: 0, duration: Math.max(1, Math.min(step.duration, 4)) }] : [];
}

export const beatSeconds = (tempo: number): number => 60 / Math.min(400, Math.max(20, tempo));

/** Marks for one chord: each sounding key labelled with its spelled name, coloured by role, the
 *  lowest note marked as the bass, and left/right hand recorded. A muted hand shows nothing. */
export function overlayFromStep(step: Step, hands: Hands): Overlay {
  const rootPc = nameToPc(step.chord_tones[0] ?? "");
  const tonePcs = new Set(step.chord_tones.map(nameToPc));
  const spelling: Record<number, string> = {};
  for (const n of [...step.chord_tones, ...step.left_names, ...step.right_names]) {
    const pc = nameToPc(n);
    if (pc !== null && spelling[pc] === undefined) spelling[pc] = n;
  }
  const sounding = [...(hands.L ? step.left : []), ...(hands.R ? step.right : [])];
  const lowest = sounding.length ? Math.min(...sounding) : -1;
  const marks = new Map<number, Mark>();
  const add = (midi: number, name: string | undefined, hand: Hand) => {
    const pc = ((midi % 12) + 12) % 12;
    const role: Mark["role"] = pc === rootPc ? "root" : tonePcs.has(pc) ? "tone" : "extra";
    marks.set(midi, { role, label: name ?? spelling[pc] ?? "", hand, bass: midi === lowest });
  };
  if (hands.L) step.left.forEach((m, i) => add(m, step.left_names[i], "L"));
  if (hands.R) step.right.forEach((m, i) => add(m, step.right_names[i], "R"));
  const title = step.roman ? `${step.symbol} (${step.roman})` : step.symbol;
  return { source: "chord", title, marks, spelling };
}

/** Where to scroll the keyboard so a chord is in view: the white-key position of its middle. */
export function centreMidi(step: Step): number | null {
  const all = [...step.left, ...step.right];
  if (!all.length) return null;
  return Math.round((Math.min(...all) + Math.max(...all)) / 2);
}

/** Beat to resume from when the displayed version changes during playback: the same point in the
 *  music, clamped to the new version's length. */
export function resumeBeat(beat: number, version: Pick<Version, "total_beats">): number {
  if (version.total_beats <= 0) return 0;
  return Math.min(Math.max(0, beat), Math.max(0, version.total_beats - EPS * 10));
}
