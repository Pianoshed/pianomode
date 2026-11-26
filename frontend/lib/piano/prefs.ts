/** Piano preferences kept in the browser. Anything stored is untrusted (it may be old, edited or
 *  corrupt), so every field is checked and falls back to its default. */

import { COMPUTER_BASE_CHOICES, DEFAULT_COMPUTER_BASE } from "./computerKeys";
import type { Accidentals, LabelMode } from "./keys";
import { type Layer, MAX_LAYERS, isSoundId } from "./sounds";

export type Prefs = {
  labels: LabelMode;
  accidentals: Accidentals;
  unicode: boolean;
  middleC: 3 | 4 | 5;
  a4: number;
  keyWidth: number; // pixels per white key
  volume: number;
  layers: Layer[];
  computerBase: number;
};

export const KEY_WIDTH_MIN = 22;
export const KEY_WIDTH_MAX = 56;

export const DEFAULT_PREFS: Prefs = {
  labels: "c",
  accidentals: "sharps",
  unicode: true,
  middleC: 4,
  a4: 440,
  keyWidth: 38,
  volume: 0.8,
  layers: [{ sound: "grand", gain: 1 }],
  computerBase: DEFAULT_COMPUTER_BASE,
};

export const STORAGE_KEY = "piano.prefs.v1";
const LABELS: readonly LabelMode[] = ["none", "c", "names", "names-octave"];

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown, lo: number, hi: number, fallback: number): number =>
  typeof v === "number" && Number.isFinite(v) && v >= lo && v <= hi ? v : fallback;

export function parseLayers(raw: unknown): Layer[] {
  if (!Array.isArray(raw)) return DEFAULT_PREFS.layers.map((l) => ({ ...l }));
  const seen = new Set<string>();
  const layers: Layer[] = [];
  for (const item of raw) {
    if (!isRecord(item) || !isSoundId(item.sound) || seen.has(item.sound)) continue;
    seen.add(item.sound);
    layers.push({ sound: item.sound, gain: num(item.gain, 0, 1, 1) });
    if (layers.length === MAX_LAYERS) break;
  }
  return layers.length ? layers : DEFAULT_PREFS.layers.map((l) => ({ ...l }));
}

export function parsePrefs(raw: unknown): Prefs {
  const d = DEFAULT_PREFS;
  if (!isRecord(raw)) return { ...d, layers: parseLayers(undefined) };
  const middleC = raw.middleC === 3 || raw.middleC === 5 ? raw.middleC : 4;
  return {
    labels: LABELS.includes(raw.labels as LabelMode) ? (raw.labels as LabelMode) : d.labels,
    accidentals: raw.accidentals === "flats" ? "flats" : "sharps",
    unicode: typeof raw.unicode === "boolean" ? raw.unicode : d.unicode,
    middleC,
    a4: num(raw.a4, 415, 466, d.a4),
    keyWidth: num(raw.keyWidth, KEY_WIDTH_MIN, KEY_WIDTH_MAX, d.keyWidth),
    volume: num(raw.volume, 0, 1, d.volume),
    layers: parseLayers(raw.layers),
    computerBase: (COMPUTER_BASE_CHOICES as readonly number[]).includes(raw.computerBase as number)
      ? (raw.computerBase as number)
      : d.computerBase,
  };
}

export function loadPrefs(storage: Pick<Storage, "getItem"> | undefined): Prefs {
  try {
    const text = storage?.getItem(STORAGE_KEY);
    return parsePrefs(text ? JSON.parse(text) : undefined);
  } catch {
    return parsePrefs(undefined);
  }
}

export function savePrefs(storage: Pick<Storage, "setItem"> | undefined, prefs: Prefs): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* private mode or full storage: preferences just will not persist */
  }
}
