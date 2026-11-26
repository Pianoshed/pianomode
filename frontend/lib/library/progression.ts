/** What a saved chord progression remembers: which movement, and how it was set up. */

import { LEVELS, type Level } from "@/lib/movements/api";

export const PROGRESSION_VERSION = 1;
export type HandMode = "both" | "L" | "R";
export type ProgressionSettings = { slug: string; tonic: string | null; level: Level; hands: HandMode; tempo: number };

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

export function serializeProgression(s: ProgressionSettings): Record<string, unknown> {
  return { v: PROGRESSION_VERSION, ...s };
}

/** Null when the save has no usable movement (so the item cannot be opened). */
export function restoreProgression(saved: unknown): ProgressionSettings | null {
  if (!isObj(saved) || typeof saved.slug !== "string" || !/^[a-z0-9][a-z0-9-]{0,79}$/.test(saved.slug)) return null;
  return {
    slug: saved.slug,
    tonic: typeof saved.tonic === "string" && /^[A-G][b#]?$/.test(saved.tonic) ? saved.tonic : null,
    level: typeof saved.level === "string" && (LEVELS as readonly string[]).includes(saved.level) ? (saved.level as Level) : "intermediate",
    hands: saved.hands === "L" || saved.hands === "R" ? saved.hands : "both",
    tempo: typeof saved.tempo === "number" && Number.isFinite(saved.tempo) ? Math.min(200, Math.max(30, Math.round(saved.tempo))) : 80,
  };
}

/** The page address that opens the movement set up as saved. */
export function progressionHref(p: ProgressionSettings): string {
  const q = new URLSearchParams({ level: p.level, hands: p.hands, tempo: String(p.tempo) });
  if (p.tonic) q.set("key", p.tonic);
  return `/progressions/${p.slug}?${q}`;
}

/** Reads the address parameters back into settings (any may be missing or wrong). */
export function progressionFromQuery(q: Record<string, string | string[] | undefined>): Partial<Omit<ProgressionSettings, "slug">> {
  const one = (k: string) => (Array.isArray(q[k]) ? (q[k] as string[])[0] : (q[k] as string | undefined));
  const parsed = restoreProgression({ slug: "x", tonic: one("key"), level: one("level"), hands: one("hands"), tempo: Number(one("tempo")) });
  const out: Partial<Omit<ProgressionSettings, "slug">> = {};
  if (!parsed) return out;
  if (one("key") && parsed.tonic) out.tonic = parsed.tonic;
  if (one("level") && (LEVELS as readonly string[]).includes(one("level") as string)) out.level = parsed.level;
  if (one("hands") === "both" || one("hands") === "L" || one("hands") === "R") out.hands = parsed.hands;
  if (one("tempo") && Number.isFinite(Number(one("tempo")))) out.tempo = parsed.tempo;
  return out;
}
