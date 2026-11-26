/** Playing the keyboard from a computer keyboard. Uses `event.code` (physical key position) so the
 *  layout works on QWERTY, AZERTY and others alike. Two rows, as in most music software: the lower
 *  row starts at `base`, the upper row one octave higher. */

import { HIGHEST_MIDI, LOWEST_MIDI } from "./keys";

const LOWER: readonly string[] = [
  "KeyZ", "KeyS", "KeyX", "KeyD", "KeyC", "KeyV", "KeyG", "KeyB", "KeyH", "KeyN", "KeyJ", "KeyM",
  "Comma", "KeyL", "Period", "Semicolon", "Slash",
];
const UPPER: readonly string[] = [
  "KeyQ", "Digit2", "KeyW", "Digit3", "KeyE", "KeyR", "Digit5", "KeyT", "Digit6", "KeyY", "Digit7",
  "KeyU", "KeyI", "Digit9", "KeyO", "Digit0", "KeyP", "BracketLeft", "Equal", "BracketRight",
];

const OFFSETS = new Map<string, number>();
LOWER.forEach((code, i) => OFFSETS.set(code, i));
UPPER.forEach((code, i) => {
  if (!OFFSETS.has(code)) OFFSETS.set(code, 12 + i);
});

/** MIDI note for a physical key, or null if the key is not a piano key (or is off the keyboard). */
export function midiForCode(code: string, base: number): number | null {
  const offset = OFFSETS.get(code);
  if (offset === undefined) return null;
  const midi = base + offset;
  return midi >= LOWEST_MIDI && midi <= HIGHEST_MIDI ? midi : null;
}

/** Keys to leave alone: shortcuts, and typing into a form control. */
export function shouldIgnoreKeyEvent(e: {
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  repeat: boolean;
  target: unknown;
}): boolean {
  if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return true;
  const t = e.target as { tagName?: string; isContentEditable?: boolean } | null;
  const tag = t?.tagName?.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || t?.isContentEditable === true;
}

export const DEFAULT_COMPUTER_BASE = 48; // C3: the lower row plays C3 to E4, the upper row C4 up
export const COMPUTER_BASE_CHOICES = [36, 48, 60] as const;

type MaybeElement = { closest?: (selector: string) => unknown } | null | undefined;

/** Should Space leave the sustain pedal alone? True when Space would activate something else: a
 *  button, link, tab, summary or a piano key (which plays on Space). Letters need no such guard,
 *  because they do nothing on a button, so playing continues after you click one. */
export function spaceBelongsToControl(target: unknown): boolean {
  const el = target as MaybeElement;
  if (typeof el?.closest !== "function") return false;
  const hit = el.closest("button, a, summary, [role='button'], [role='tab']");
  return hit !== null && hit !== undefined;
}
