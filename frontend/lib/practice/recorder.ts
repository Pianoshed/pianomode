/** Collects the notes a player presses, in session seconds (the same seconds as the practice
 *  clock), ready to send to the scoring API. */

export type Recorded = { midi: number; time_s: number; off_time_s?: number };
export const MAX_RECORDED = 5000;

export class Recorder {
  private done: Recorded[] = [];
  private open = new Map<number, Recorded>();

  clear(): void {
    this.done = [];
    this.open.clear();
  }

  noteOn(midi: number, seconds: number): void {
    if (!(seconds >= 0) || this.done.length + this.open.size >= MAX_RECORDED) return;
    const again = this.open.get(midi);
    if (again) this.done.push(again); // a repeated press without a release: keep the first, open anew
    this.open.set(midi, { midi, time_s: seconds });
  }

  noteOff(midi: number, seconds: number): void {
    const n = this.open.get(midi);
    if (!n) return;
    this.open.delete(midi);
    this.done.push(seconds >= n.time_s ? { ...n, off_time_s: seconds } : n);
  }

  /** Everything played so far, in time order. Keys still down have no release time. */
  notes(): Recorded[] {
    return [...this.done, ...this.open.values()].sort((a, b) => a.time_s - b.time_s || a.midi - b.midi);
  }

  /** The notes that started within `[from, to]` seconds: what one pass needs. */
  between(from: number, to: number): Recorded[] {
    return this.notes().filter((n) => n.time_s >= from && n.time_s <= to);
  }
}

/** Delay between the audio clock and what the player hears, which scoring should remove. The
 *  browser reports it on most engines; where it does not, the answer is 0 and the player can type
 *  one in. Kept to 0 to 500 ms. */
export function reportedLatencyMs(ctx: { outputLatency?: number; baseLatency?: number } | null): number {
  if (!ctx) return 0;
  const seconds = ctx.outputLatency || ctx.baseLatency || 0;
  return Math.min(500, Math.max(0, Math.round(seconds * 1000)));
}
