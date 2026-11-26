/** Which keys are down, counted per source, so a note held by the mouse and the computer keyboard
 *  at once stays down until both let go. Immutable: every change returns a new value. */

export type Source = "pointer" | "keyboard" | "midi" | "program";

export type Held = ReadonlyMap<number, ReadonlyMap<Source, number>>;
export const EMPTY_HELD: Held = new Map();

export function press(held: Held, midi: number, source: Source): Held {
  const next = new Map(held);
  const sources = new Map(next.get(midi) ?? []);
  sources.set(source, (sources.get(source) ?? 0) + 1);
  next.set(midi, sources);
  return next;
}

export function release(held: Held, midi: number, source: Source): Held {
  const sources = held.get(midi);
  const count = sources?.get(source);
  if (!sources || !count) return held; // releasing a note that is not down changes nothing
  const next = new Map(held);
  const updated = new Map(sources);
  if (count > 1) updated.set(source, count - 1);
  else updated.delete(source);
  if (updated.size === 0) next.delete(midi);
  else next.set(midi, updated);
  return next;
}

export const releaseAll = (_held: Held): Held => EMPTY_HELD;

/** Sounding notes, low to high. */
export function heldNotes(held: Held): number[] {
  return [...held.keys()].sort((a, b) => a - b);
}

export const isHeld = (held: Held, midi: number): boolean => held.has(midi);
