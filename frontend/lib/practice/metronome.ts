/** The metronome engine (Phase 7, step 2): a lookahead scheduler and a click sound.
 *
 *  Browsers run JavaScript timers late and unevenly, but the audio clock is exact. So clicks are
 *  not played when a timer fires; the timer only *looks ahead* a fraction of a second and hands
 *  each upcoming click to the audio clock with its exact start time. The scheduler takes its
 *  clock, timers and sound as parameters, so it is tested with a fake clock and no real audio. */

import type { Click } from "./clock";

export type SchedulerDeps = {
  now: () => number; // audio-clock seconds
  play: (atSeconds: number, click: Click) => void;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (id: unknown) => void;
  lookaheadSeconds?: number; // how far ahead to hand clicks to the audio clock
  intervalMs?: number; // how often to look ahead
  startDelaySeconds?: number; // gap before session second 0, so the first click is never in the past
  lateToleranceSeconds?: number; // a click later than this is dropped, not played in a bunch
};

export type StartOptions = {
  endSeconds?: number; // session second at which `onEnd` fires (the end of the plan)
  onEnd?: () => void;
  onClick?: (click: Click, atSeconds: number) => void;
};

export class ClickScheduler {
  private timer: unknown = null;
  private source: Iterator<Click> | null = null;
  private pending: Click | null = null;
  private origin: number | null = null;
  private opts: StartOptions = {};
  private dropped = 0;
  private exhausted = false;

  constructor(private readonly deps: SchedulerDeps) {}

  get running(): boolean {
    return this.timer !== null;
  }
  /** Clicks skipped because the timer was starved for too long (a hidden tab, a busy page). */
  get droppedClicks(): number {
    return this.dropped;
  }
  /** Audio-clock time of session second 0, or null when stopped. */
  get startedAt(): number | null {
    return this.origin;
  }
  /** Seconds since the session started, on the audio clock; null when stopped. */
  sessionSeconds(): number | null {
    return this.origin === null ? null : this.deps.now() - this.origin;
  }

  /** Start from session second 0. Any run in progress is stopped first. */
  start(clicks: Iterator<Click>, opts: StartOptions = {}): void {
    this.stop();
    this.source = clicks;
    this.pending = null;
    this.exhausted = false;
    this.dropped = 0;
    this.opts = opts;
    this.origin = this.deps.now() + (this.deps.startDelaySeconds ?? 0.05);
    this.tick();
    if (this.origin !== null) this.timer = this.deps.setTimer(() => this.loop(), this.deps.intervalMs ?? 25);
  }

  stop(): void {
    if (this.timer !== null) this.deps.clearTimer(this.timer);
    this.timer = null;
    this.source = null;
    this.pending = null;
    this.origin = null;
  }

  private loop(): void {
    if (this.origin === null) return;
    this.tick();
    if (this.origin !== null) this.timer = this.deps.setTimer(() => this.loop(), this.deps.intervalMs ?? 25);
  }

  private tick(): void {
    const origin = this.origin;
    const source = this.source;
    if (origin === null || source === null) return;
    const now = this.deps.now();
    const horizon = now + (this.deps.lookaheadSeconds ?? 0.2);
    const late = this.deps.lateToleranceSeconds ?? 0.1;
    for (;;) {
      if (!this.pending && !this.exhausted) {
        const next = source.next();
        if (next.done) this.exhausted = true;
        else this.pending = next.value;
      }
      const click = this.pending;
      if (!click) break;
      const at = origin + click.time;
      if (at > horizon) break;
      this.pending = null;
      if (at < now - late) {
        this.dropped += 1;
        continue;
      }
      this.deps.play(at, click);
      this.opts.onClick?.(click, at);
    }
    const end = this.opts.endSeconds;
    const finished = end !== undefined ? now >= origin + end : this.exhausted && this.pending === null;
    if (finished) {
      const done = this.opts.onEnd;
      this.stop();
      done?.();
    }
  }
}

// ---------------------------------------------------------------- the click sound

export const CLICK_PITCH = { accent: 1500, beat: 1000, countIn: 700 } as const;

export type ClickSound = { frequency: number; gain: number };

/** Pitch and loudness for a click: bar lines are higher and louder, count-in clicks are lower. */
export function clickSound(click: Pick<Click, "accent" | "countIn">, volume: number): ClickSound {
  const v = Math.min(1, Math.max(0, volume));
  const frequency = click.countIn ? CLICK_PITCH.countIn : click.accent ? CLICK_PITCH.accent : CLICK_PITCH.beat;
  return { frequency, gain: click.accent ? v : v * 0.6 };
}

/** A short sine blip at an exact audio-clock time. Shares the audio context with the piano so
 *  clicks and notes use one clock and cannot drift apart. */
export function createClicker(ctx: AudioContext, volume: () => number): (atSeconds: number, click: Click) => void {
  return (at, click) => {
    const { frequency, gain } = clickSound(click, volume());
    if (gain <= 0) return;
    const osc = ctx.createOscillator();
    const env = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(frequency, at);
    env.gain.setValueAtTime(0.0001, at);
    env.gain.exponentialRampToValueAtTime(gain, at + 0.002);
    env.gain.exponentialRampToValueAtTime(0.0001, at + 0.05);
    osc.connect(env).connect(ctx.destination);
    osc.start(at);
    osc.stop(at + 0.06);
  };
}
