/** Turns theory API responses into marks on keys. All musical content (which notes, which
 *  spelling, which interval) comes from the API; this file only decides where to put the dots. */

import { KEYS } from "./keys";
import type { Candidate, ChordConstruct, ScaleResult, VoicingsResult } from "./theoryApi";

export type MarkRole = "root" | "tone" | "extra" | "scale";
export type Mark = {
  role: MarkRole;
  /** Short text inside the dot: an interval (R, 3, ♭7), a scale degree, or a note name. */
  label: string;
  hand?: "L" | "R";
  /** This is the lowest sounding note of the chord. */
  bass?: boolean;
};
export type MarkMap = ReadonlyMap<number, Mark>;

export type Overlay = {
  source: "chord" | "scale" | "identify";
  title: string;
  marks: MarkMap;
  /** Note spellings by pitch class, so key labels agree with the chord or scale shown. */
  spelling: Readonly<Record<number, string>>;
};

const LETTER_PC: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

/** Pitch class of a spelled note name such as "Eb", "F#", "B#" or "Bbb". Notation only. */
export function nameToPc(name: string): number | null {
  const m = /^([A-G])([#b♯♭]*)$/.exec(name.replace(/\d+$/, "").replace(/𝄪/g, "##").replace(/𝄫/g, "bb"));
  if (!m) return null;
  let pc = LETTER_PC[m[1] as string] as number;
  for (const ch of m[2] as string) pc += ch === "#" || ch === "♯" ? 1 : -1;
  return ((pc % 12) + 12) % 12;
}

/** The text for an interval short name, as chord symbols write it: P1 -> R, m3 -> ♭3, A5 -> ♯5. */
export function intervalLabel(short: string): string {
  const m = /^(P|M|m|A|d|AA|dd)(\d+)$/.exec(short);
  if (!m) return short;
  const [, quality, number] = m as unknown as [string, string, string];
  if (quality === "P" && number === "1") return "R";
  if (quality === "m" || quality === "d") return `♭${number}`;
  if (quality === "dd") return `𝄫${number}`;
  if (quality === "A") return `♯${number}`;
  if (quality === "AA") return `𝄪${number}`;
  return number;
}

const stripOctave = (name: string): string => name.replace(/-?\d+$/, "");

function spellingOf(names: readonly string[]): Record<number, string> {
  const out: Record<number, string> = {};
  for (const n of names) {
    const pc = nameToPc(n);
    if (pc !== null && out[pc] === undefined) out[pc] = stripOctave(n);
  }
  return out;
}

function toneMarks(res: ChordConstruct): Map<number, { role: MarkRole; label: string }> {
  const { tones, pitch_classes: pcs } = res.chord;
  const byPc = new Map<number, { role: MarkRole; label: string }>();
  tones.forEach((t, i) => {
    const pc = pcs[i];
    if (pc === undefined) return;
    byPc.set(pc, { role: t.interval === "P1" ? "root" : "tone", label: intervalLabel(t.interval) });
  });
  return byPc;
}

/** A chord: either the exact keys of its voicing, or every key with a chord tone in all octaves. */
export function overlayFromChord(res: ChordConstruct, everywhere: boolean): Overlay {
  const byPc = toneMarks(res);
  const marks = new Map<number, Mark>();
  const bassMidi = Math.min(...res.midi_notes);
  if (everywhere) {
    for (const k of KEYS) {
      const t = byPc.get(k.pc);
      if (t) marks.set(k.midi, { ...t });
    }
  } else {
    for (const midi of res.midi_notes) {
      const t = byPc.get(((midi % 12) + 12) % 12) ?? { role: "extra" as const, label: "bass" };
      marks.set(midi, { ...t, bass: midi === bassMidi });
    }
  }
  return {
    source: "chord",
    title: res.chord.symbol,
    marks,
    spelling: spellingOf([...res.chord.tones.map((t) => t.name), ...(everywhere ? [] : res.notes.map((n) => n.name))]),
  };
}

/** A scale: every key in the scale, labelled with its degree. */
export function overlayFromScale(res: ScaleResult): Overlay {
  const byPc = new Map<number, Mark>();
  res.keyboard.forEach((n, i) => {
    const deg = res.degrees[i];
    if (deg) byPc.set(n.pitch_class, { role: deg.number === 1 ? "root" : "scale", label: String(deg.number) });
  });
  const marks = new Map<number, Mark>();
  for (const k of KEYS) {
    const m = byPc.get(k.pc);
    if (m) marks.set(k.midi, { ...m });
  }
  return {
    source: "scale",
    title: `${res.root} ${res.scale.name.toLowerCase()}`,
    marks,
    spelling: spellingOf(res.notes),
  };
}

/** A suggested two-hand voicing: its exact keys, marked left or right hand. */
export function overlayFromVoicing(chord: ChordConstruct, voicings: VoicingsResult): Overlay | null {
  const first = voicings.voicings[0]?.voicing;
  if (!first) return null;
  const byPc = toneMarks(chord);
  const all = [...first.left, ...first.right];
  const lowest = Math.min(...all);
  const marks = new Map<number, Mark>();
  const add = (midi: number, hand: "L" | "R") => {
    const t = byPc.get(((midi % 12) + 12) % 12) ?? { role: "extra" as const, label: "+" };
    marks.set(midi, { ...t, hand, bass: midi === lowest });
  };
  first.left.forEach((m) => add(m, "L"));
  first.right.forEach((m) => add(m, "R"));
  return {
    source: "chord",
    title: `${chord.chord.symbol}, both hands`,
    marks,
    spelling: spellingOf([...chord.chord.tones.map((t) => t.name), ...first.left_names, ...first.right_names]),
  };
}

/** One reading of the keys being played: chord tones, extras and the bass, spelled as the reading spells them. */
export function overlayFromCandidate(c: Candidate, played: readonly number[]): Overlay {
  const rootPc = nameToPc(c.root);
  const detected = new Set(c.detected_tones.map(nameToPc));
  const extra = new Set(c.extra_tones.map(nameToPc));
  const lowest = played.length ? Math.min(...played) : -1;
  const spelling = spellingOf([...c.required_tones, ...c.detected_tones, ...c.extra_tones]);
  const marks = new Map<number, Mark>();
  for (const midi of played) {
    const pc = ((midi % 12) + 12) % 12;
    const role: MarkRole = pc === rootPc ? "root" : extra.has(pc) ? "extra" : detected.has(pc) ? "tone" : "extra";
    marks.set(midi, { role, label: spelling[pc] ?? "", bass: midi === lowest });
  }
  return { source: "identify", title: c.symbol, marks, spelling };
}
