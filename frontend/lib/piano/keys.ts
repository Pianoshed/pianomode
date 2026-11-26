/** Geometry and labelling for an 88-key keyboard (A0 = MIDI 21 to C8 = MIDI 108).
 *  Pure functions only, so they are unit-tested; the components just draw what this says. */

export const LOWEST_MIDI = 21;
export const HIGHEST_MIDI = 108;
export const BLACK_WIDTH = 0.6; // in white-key widths
export const BLACK_HEIGHT = 0.62; // as a fraction of the keyboard height

const BLACK_PCS = new Set([1, 3, 6, 8, 10]);
// Real black keys sit slightly off the gap between their neighbours (in white-key widths).
const BLACK_OFFSET: Record<number, number> = { 1: -0.07, 3: 0.07, 6: -0.08, 8: 0, 10: 0.08 };

export type PianoKey = {
  midi: number;
  pc: number;
  /** Scientific pitch octave number of this key (C4 = middle C = MIDI 60). */
  octave: number;
  black: boolean;
  /** Left edge in white-key widths. */
  x: number;
  width: number;
};

export const isBlackPc = (pc: number): boolean => BLACK_PCS.has(((pc % 12) + 12) % 12);
export const isBlack = (midi: number): boolean => isBlackPc(midi);

function buildKeys(): PianoKey[] {
  const keys: PianoKey[] = [];
  let whites = 0;
  for (let midi = LOWEST_MIDI; midi <= HIGHEST_MIDI; midi++) {
    const pc = midi % 12;
    const octave = Math.floor(midi / 12) - 1;
    if (!isBlackPc(pc)) {
      keys.push({ midi, pc, octave, black: false, x: whites, width: 1 });
      whites++;
    } else {
      // A black key sits on the boundary after the white key just placed.
      const centre = whites + (BLACK_OFFSET[pc] ?? 0);
      keys.push({ midi, pc, octave, black: true, x: centre - BLACK_WIDTH / 2, width: BLACK_WIDTH });
    }
  }
  return keys;
}

export const KEYS: readonly PianoKey[] = buildKeys();
export const WHITE_KEYS: readonly PianoKey[] = KEYS.filter((k) => !k.black);
export const BLACK_KEYS: readonly PianoKey[] = KEYS.filter((k) => k.black);
export const WHITE_COUNT = WHITE_KEYS.length; // 52

const KEY_BY_MIDI = new Map(KEYS.map((k) => [k.midi, k]));
export const keyFor = (midi: number): PianoKey | undefined => KEY_BY_MIDI.get(midi);
export const inRange = (midi: number): boolean => midi >= LOWEST_MIDI && midi <= HIGHEST_MIDI;

/** The key under a point: x in white-key widths from the left edge, y as a fraction (0 = top). */
export function midiFromPoint(x: number, y: number): number | null {
  if (!(x >= 0 && x < WHITE_COUNT && y >= 0 && y <= 1)) return null;
  if (y <= BLACK_HEIGHT) {
    for (const k of BLACK_KEYS) if (x >= k.x && x < k.x + k.width) return k.midi;
  }
  return WHITE_KEYS[Math.floor(x)]?.midi ?? null;
}

/** Harder presses lower on the key, as on a real keyboard. Result is a MIDI velocity 1-127. */
export function velocityFromY(y: number, black: boolean): number {
  const height = black ? BLACK_HEIGHT : 1;
  const rel = Math.min(1, Math.max(0, y / height));
  return Math.round(36 + 91 * rel);
}

export const midiToFrequency = (midi: number, a4 = 440): number => a4 * 2 ** ((midi - 69) / 12);

// ------------------------------------------------------------------ labels

export type LabelMode = "none" | "c" | "names" | "names-octave";
export type Accidentals = "sharps" | "flats";

const SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

export type LabelOptions = {
  mode: LabelMode;
  accidentals: Accidentals;
  /** Octave number given to middle C (60). 4 is scientific pitch, 3 and 5 are also in use. */
  middleC?: number;
  /** Spellings from the theory engine by pitch class (for example 3 -> "D#" or 11 -> "Cb"),
   *  which win over the sharps/flats preference so the keys agree with the chord or key. */
  spelling?: Readonly<Record<number, string>>;
  /** Show real sharp and flat signs instead of # and b. */
  unicode?: boolean;
};

export function pitchClassName(pc: number, accidentals: Accidentals): string {
  const table = accidentals === "sharps" ? SHARP_NAMES : FLAT_NAMES;
  return table[((pc % 12) + 12) % 12] as string;
}

const prettify = (name: string): string =>
  name.replace(/##/g, "𝄪").replace(/bb/g, "𝄫").replace(/#/g, "♯").replace(/(?<=[A-G𝄫])b/g, "♭");

/** The note name for a key, without octave. Honours a spelling override for its pitch class. */
export function spelledName(midi: number, opts: Pick<LabelOptions, "accidentals" | "spelling">): string {
  const pc = ((midi % 12) + 12) % 12;
  return opts.spelling?.[pc] ?? pitchClassName(pc, opts.accidentals);
}

/** Octave number to print for a spelled name: B# belongs to the octave below its sounding pitch,
 *  and Cb to the octave above (B#3 and C4 are the same key). */
export function octaveFor(midi: number, name: string, middleC = 4): number {
  let octave = Math.floor(midi / 12) - 1 + (middleC - 4);
  if (name.startsWith("B") && name.includes("#")) octave -= 1;
  else if (name.startsWith("C") && name.includes("b")) octave += 1;
  return octave;
}

/** The text on a key, or "" if this key has none under the chosen mode. */
export function noteLabel(midi: number, opts: LabelOptions): string {
  if (opts.mode === "none") return "";
  const pc = ((midi % 12) + 12) % 12;
  if (opts.mode === "c" && pc !== 0) return "";
  const name = spelledName(midi, opts);
  const withOctave = opts.mode === "c" || opts.mode === "names-octave";
  const text = withOctave ? `${name}${octaveFor(midi, name, opts.middleC)}` : name;
  return opts.unicode ? prettify(text) : text;
}

/** Spoken-style name for assistive technology: "C sharp 4" is clearer than "C#4". */
export function accessibleName(midi: number, opts: Pick<LabelOptions, "accidentals" | "spelling" | "middleC">): string {
  const name = spelledName(midi, opts);
  const words = name
    .replace(/##/g, " double sharp")
    .replace(/bb/g, " double flat")
    .replace(/#/g, " sharp")
    .replace(/(?<=[A-G])b/g, " flat");
  return `${words} ${octaveFor(midi, name, opts.middleC)}`;
}
