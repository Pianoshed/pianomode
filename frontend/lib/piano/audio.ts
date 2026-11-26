/** Web Audio playback. The browser only allows sound after a user gesture, so nothing is created
 *  until `resume()` is called from a click, key press or touch. All the sound design is in
 *  `sounds.ts`; this file builds nodes from a plan and manages the pedal and voice limits. */

import { type Layer, type VoicePlan, planLayers } from "./sounds";

const MAX_VOICES = 96;

class Voice {
  private readonly oscillators: OscillatorNode[] = [];
  private readonly releaseGain: GainNode;
  private ended = false;
  readonly midi: number;

  constructor(
    private readonly ctx: AudioContext,
    destination: AudioNode,
    private readonly plan: VoicePlan,
    midi: number,
    when: number,
    private readonly onEnded: (v: Voice) => void,
  ) {
    this.midi = midi;
    const env = ctx.createGain();
    env.gain.setValueAtTime(0.0001, when);
    env.gain.linearRampToValueAtTime(plan.peak, when + plan.attack);
    if (plan.decayTau !== null) env.gain.setTargetAtTime(0, when + plan.attack, plan.decayTau);
    // The release lives on its own gain node, in series, so a note can be released at a time that
    // is already scheduled without having to know what the envelope's value will be then.
    this.releaseGain = ctx.createGain();
    env.connect(this.releaseGain).connect(destination);

    let entry: AudioNode = env;
    if (plan.lowpass) {
      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = plan.lowpass.cutoff;
      filter.Q.value = plan.lowpass.q;
      filter.connect(env);
      entry = filter;
    }
    for (const o of plan.oscillators) {
      const osc = ctx.createOscillator();
      osc.type = o.type;
      osc.frequency.value = o.frequency;
      osc.detune.value = o.detune;
      const g = ctx.createGain();
      g.gain.value = o.gain;
      osc.connect(g).connect(entry);
      if (plan.fm) {
        const mod = ctx.createOscillator();
        mod.frequency.value = plan.fm.frequency;
        const depth = ctx.createGain();
        depth.gain.setValueAtTime(plan.fm.depth, when);
        depth.gain.setTargetAtTime(0, when, plan.fm.decay);
        mod.connect(depth).connect(osc.frequency);
        mod.start(when);
        this.oscillators.push(mod);
      }
      osc.start(when);
      this.oscillators.push(osc);
    }
    const first = this.oscillators[0];
    if (first) first.onended = () => this.dispose();
  }

  /** Let go at `when` (audio-clock seconds). */
  release(when: number, seconds = this.plan.release): void {
    if (this.ended) return;
    this.releaseGain.gain.setValueAtTime(1, when);
    this.releaseGain.gain.setTargetAtTime(0, when, seconds / 4);
    const stopAt = when + seconds * 1.4 + 0.05;
    for (const o of this.oscillators) {
      try {
        o.stop(stopAt);
      } catch {
        /* already stopped */
      }
    }
  }

  private dispose(): void {
    if (this.ended) return;
    this.ended = true;
    try {
      this.releaseGain.disconnect();
    } catch {
      /* already disconnected */
    }
    this.onEnded(this);
  }

  kill(): void {
    this.release(this.ctx.currentTime, 0.04);
  }
}

export type ScheduledEvent = { notes: readonly number[]; start: number; duration: number };
export type TimedNoteSpec = { midi: number; startSeconds: number; durationSeconds: number };
export type Playback = { stop: () => void; seconds: number };

export class PianoAudio {
  private ctx: AudioContext | null = null;
  private out: GainNode | null = null;
  private readonly live = new Map<number, Voice[]>(); // voices for keys that are down or pedalled
  private readonly all = new Set<Voice>();
  private readonly down = new Set<number>();
  private readonly pedalled = new Set<number>();
  private pedal = false;
  private volume = 0.8;
  private a4 = 440;

  get ready(): boolean {
    return this.ctx !== null && this.ctx.state === "running";
  }

  /** The audio context once `resume()` has run, so other sounds (the metronome) can share its
   *  clock with the piano and stay in step with it. */
  get context(): AudioContext | null {
    return this.ctx;
  }

  /** Call from a user gesture. Returns false if this browser has no Web Audio. */
  async resume(): Promise<boolean> {
    if (typeof window === "undefined" || typeof window.AudioContext === "undefined") return false;
    if (!this.ctx) {
      this.ctx = new AudioContext({ latencyHint: "interactive" });
      const comp = this.ctx.createDynamicsCompressor(); // protects the ears when many notes stack
      comp.threshold.value = -14;
      comp.ratio.value = 6;
      this.out = this.ctx.createGain();
      this.out.gain.value = this.volume;
      this.out.connect(comp).connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
    return this.ctx.state === "running";
  }

  setVolume(volume: number): void {
    this.volume = Math.min(1, Math.max(0, volume));
    if (this.out && this.ctx) this.out.gain.setTargetAtTime(this.volume, this.ctx.currentTime, 0.02);
  }

  setTuning(a4: number): void {
    this.a4 = a4;
  }

  private start(midi: number, velocity: number, layers: readonly Layer[], when: number): Voice[] {
    const ctx = this.ctx;
    const out = this.out;
    if (!ctx || !out) return [];
    const voices = planLayers(layers, midi, velocity, this.a4).map(
      (plan) => new Voice(ctx, out, plan, midi, when, (v) => this.forget(v)),
    );
    for (const v of voices) this.all.add(v);
    while (this.all.size > MAX_VOICES) {
      const oldest = this.all.values().next().value as Voice | undefined;
      if (!oldest) break;
      oldest.kill();
      this.all.delete(oldest);
    }
    return voices;
  }

  private forget(v: Voice): void {
    this.all.delete(v);
    const list = this.live.get(v.midi);
    if (list) {
      const rest = list.filter((x) => x !== v);
      if (rest.length) this.live.set(v.midi, rest);
      else this.live.delete(v.midi);
    }
  }

  noteOn(midi: number, velocity: number, layers: readonly Layer[]): void {
    if (!this.ctx) return;
    // Striking a key again damps the previous note on that key first, as a real piano does.
    for (const old of this.live.get(midi) ?? []) old.release(this.ctx.currentTime, 0.08);
    this.pedalled.delete(midi);
    this.down.add(midi);
    this.live.set(midi, this.start(midi, velocity, layers, this.ctx.currentTime));
  }

  noteOff(midi: number): void {
    this.down.delete(midi);
    if (this.pedal) {
      this.pedalled.add(midi);
      return;
    }
    this.releaseLive(midi);
  }

  private releaseLive(midi: number): void {
    const ctx = this.ctx;
    if (!ctx) return;
    for (const v of this.live.get(midi) ?? []) v.release(ctx.currentTime);
    this.live.delete(midi);
  }

  setSustain(on: boolean): void {
    this.pedal = on;
    if (on) return;
    for (const midi of this.pedalled) if (!this.down.has(midi)) this.releaseLive(midi);
    this.pedalled.clear();
  }

  /** Stop everything now (for the panic button, leaving the page, or switching sounds). */
  allNotesOff(): void {
    for (const v of [...this.all]) v.kill();
    this.live.clear();
    this.down.clear();
    this.pedalled.clear();
  }

  /** Play notes at exact seconds after `origin` (an audio-clock time), so they line up with other
   *  scheduled sounds such as the metronome. */
  scheduleAt(origin: number, notes: readonly TimedNoteSpec[], layers: readonly Layer[], velocity = 84): Playback {
    const ctx = this.ctx;
    if (!ctx) return { stop: () => undefined, seconds: 0 };
    const voices: Voice[] = [];
    let end = 0;
    for (const n of notes) {
      const on = Math.max(ctx.currentTime, origin + n.startSeconds);
      const off = on + n.durationSeconds * 0.96;
      end = Math.max(end, off);
      for (const v of this.start(n.midi, velocity, layers, on)) {
        v.release(off);
        voices.push(v);
      }
    }
    return { stop: () => voices.forEach((v) => v.kill()), seconds: end - ctx.currentTime };
  }

  /** Play notes at beat positions. `tempo` is beats per minute. Returns a handle to cut it short. */
  schedule(events: readonly ScheduledEvent[], tempo: number, layers: readonly Layer[], velocity = 84): Playback {
    const ctx = this.ctx;
    if (!ctx) return { stop: () => undefined, seconds: 0 };
    const spb = 60 / Math.min(400, Math.max(20, tempo));
    const t0 = ctx.currentTime + 0.06;
    const voices: Voice[] = [];
    let end = 0;
    for (const e of events) {
      const on = t0 + e.start * spb;
      const off = on + e.duration * spb * 0.96;
      end = Math.max(end, off);
      for (const midi of e.notes) {
        for (const v of this.start(midi, velocity, layers, on)) {
          v.release(off);
          voices.push(v);
        }
      }
    }
    return { stop: () => voices.forEach((v) => v.kill()), seconds: end - ctx.currentTime };
  }
}
