/** Five synthesised sounds, described as data. `voicePlan` turns a sound, a note and a velocity into
 *  a plain description of the oscillators and envelope; `audio.ts` only has to build nodes from it.
 *  These are synthesised approximations, not recordings of real instruments. */

import { midiToFrequency } from "./keys";

export type SoundId = "grand" | "electric" | "organ" | "strings" | "bells";
export const SOUND_IDS: readonly SoundId[] = ["grand", "electric", "organ", "strings", "bells"];

export const SOUND_INFO: Record<SoundId, { label: string; description: string }> = {
  grand: { label: "Grand piano", description: "Bright attack that fades, longer in the low notes." },
  electric: { label: "Electric piano", description: "Soft, bell-like tine with a short bark at the start." },
  organ: { label: "Organ", description: "Steady tone for as long as the key is down." },
  strings: { label: "Strings", description: "Slow swell with a warm, wide tone." },
  bells: { label: "Bells", description: "Clear, ringing tone with a long shimmer." },
};

export const isSoundId = (v: unknown): v is SoundId => SOUND_IDS.includes(v as SoundId);

export type Layer = { sound: SoundId; gain: number };
export const MAX_LAYERS = 3;

export type OscPlan = { frequency: number; gain: number; type: OscillatorType; detune: number };
export type VoicePlan = {
  oscillators: OscPlan[];
  /** Frequency modulation applied to every oscillator: depth in Hz, fading with time constant `decay`. */
  fm: { frequency: number; depth: number; decay: number } | null;
  lowpass: { cutoff: number; q: number } | null;
  attack: number;
  peak: number;
  /** Time constant of the fade while the key is held, or null if the sound holds steady. */
  decayTau: number | null;
  release: number;
};

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
/** 0-1 loudness from MIDI velocity, with a gentle curve so soft playing stays soft. */
export const velocityGain = (velocity: number): number => (clamp(velocity, 1, 127) / 127) ** 1.4;

function additive(
  base: number,
  ratios: readonly number[],
  gains: readonly number[],
  type: OscillatorType,
): OscPlan[] {
  const nyquistSafe = 18000;
  const out: OscPlan[] = [];
  ratios.forEach((r, i) => {
    const frequency = base * r;
    if (frequency < nyquistSafe) out.push({ frequency, gain: gains[i] ?? 0, type, detune: 0 });
  });
  return out;
}

export function voicePlan(sound: SoundId, midi: number, velocity: number, a4 = 440): VoicePlan {
  const f = midiToFrequency(midi, a4);
  const v = velocityGain(velocity);
  const register = (midi - 60) / 12; // octaves above middle C
  const loud = 0.3 * v;

  switch (sound) {
    case "grand": {
      // Harder playing is brighter: upper partials gain with velocity. A little inharmonicity
      // (stretched partials) grows with pitch, as in a real string.
      const bright = 0.35 + 0.65 * (velocity / 127);
      const b = 0.0002 * 2 ** register;
      // Normalised so the fundamental is exactly the note's pitch; only the upper partials stretch.
      const ratios = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => n * Math.sqrt((1 + b * n * n) / (1 + b)));
      const base = [1, 0.55, 0.38, 0.22, 0.14, 0.09, 0.06, 0.04];
      const gains = base.map((g, i) => g * bright ** i);
      return {
        oscillators: additive(f, ratios, gains, "sine"),
        fm: null,
        lowpass: null,
        attack: 0.004,
        peak: loud,
        decayTau: clamp(2.6 * 2 ** (-register / 1.6), 0.35, 6),
        release: 0.22,
      };
    }
    case "electric":
      return {
        oscillators: [
          { frequency: f, gain: 0.85, type: "sine", detune: 0 },
          { frequency: f * 2, gain: 0.12, type: "sine", detune: 0 },
        ],
        fm: { frequency: f * 14, depth: f * 0.9 * (0.35 + 0.65 * v), decay: 0.32 },
        lowpass: null,
        attack: 0.006,
        peak: loud * 1.1,
        decayTau: clamp(1.9 * 2 ** (-register / 1.8), 0.3, 4),
        release: 0.18,
      };
    case "organ":
      return {
        oscillators: additive(
          f,
          [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8],
          [0.5, 0.8, 0.4, 0.6, 0.3, 0.3, 0.14, 0.1, 0.08],
          "sine",
        ),
        fm: null,
        lowpass: { cutoff: 7000, q: 0.5 },
        attack: 0.014,
        peak: loud * 0.7,
        decayTau: null,
        release: 0.07,
      };
    case "strings":
      return {
        oscillators: [-9, 0, 9].map((detune) => ({ frequency: f, gain: 0.34, type: "sawtooth" as const, detune })),
        fm: null,
        lowpass: { cutoff: clamp(f * 5, 600, 7000), q: 0.7 },
        attack: 0.28,
        peak: loud * 0.55,
        decayTau: null,
        release: 0.7,
      };
    case "bells":
      return {
        oscillators: additive(f, [1, 2.76, 5.4, 8.93], [1, 0.5, 0.28, 0.16], "sine"),
        fm: null,
        lowpass: null,
        attack: 0.002,
        peak: loud * 0.8,
        decayTau: clamp(3.2 * 2 ** (-(midi - 72) / 24), 0.6, 7),
        release: 0.5,
      };
  }
}

/** Plans for every active layer. Layer gains are shared out so stacking sounds adds fullness, not
 *  volume (the total never exceeds one layer's worth of headroom times 1.3). */
export function planLayers(layers: readonly Layer[], midi: number, velocity: number, a4 = 440): VoicePlan[] {
  const active = layers.filter((l) => l.gain > 0);
  const total = active.reduce((s, l) => s + l.gain, 0);
  const norm = total > 1 ? 1 / total : 1;
  return active.map((l) => {
    const plan = voicePlan(l.sound, midi, velocity, a4);
    const sum = plan.oscillators.reduce((s, o) => s + o.gain, 0) || 1;
    const scale = (l.gain * norm) / sum;
    return {
      ...plan,
      oscillators: plan.oscillators.map((o) => ({ ...o, gain: o.gain * scale })),
      peak: plan.peak * 1.5,
    };
  });
}
