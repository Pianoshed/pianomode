import { describe, expect, it } from "vitest";
import { SOUND_IDS, SOUND_INFO, planLayers, velocityGain, voicePlan } from "./sounds";

describe("sound plans", () => {
  it("offers five sounds, each described", () => {
    expect(SOUND_IDS).toHaveLength(5);
    for (const id of SOUND_IDS) expect(SOUND_INFO[id].label.length).toBeGreaterThan(2);
  });

  it("puts the fundamental at the note's frequency, with the tuning reference applied", () => {
    const grand = voicePlan("grand", 69, 100);
    expect(grand.oscillators[0]?.frequency).toBeCloseTo(440, 6);
    expect(voicePlan("grand", 69, 100, 432).oscillators[0]?.frequency).toBeCloseTo(432, 6);
    expect(voicePlan("organ", 69, 100).oscillators.map((o) => o.frequency)).toContain(880);
  });

  it("stretches the grand piano's upper partials slightly (inharmonicity)", () => {
    const p = voicePlan("grand", 60, 100).oscillators;
    const f0 = p[0]?.frequency ?? 1;
    expect((p[7]?.frequency ?? 0) / f0).toBeGreaterThan(8);
    expect((p[7]?.frequency ?? 0) / f0).toBeLessThan(8.1);
  });

  it("is brighter when played harder and louder when played harder", () => {
    const soft = voicePlan("grand", 60, 30);
    const hard = voicePlan("grand", 60, 120);
    const ratio = (p: typeof soft) => (p.oscillators[5]?.gain ?? 0) / (p.oscillators[0]?.gain ?? 1);
    expect(ratio(hard)).toBeGreaterThan(ratio(soft));
    expect(hard.peak).toBeGreaterThan(soft.peak);
    expect(velocityGain(127)).toBe(1);
    expect(velocityGain(0)).toBeGreaterThan(0); // clamps to the softest note rather than silence
  });

  it("makes low piano notes ring longer than high ones, and keeps organ and strings steady", () => {
    expect(voicePlan("grand", 36, 90).decayTau ?? 0).toBeGreaterThan(voicePlan("grand", 96, 90).decayTau ?? 0);
    expect(voicePlan("organ", 60, 90).decayTau).toBeNull();
    expect(voicePlan("strings", 60, 90).decayTau).toBeNull();
    expect(voicePlan("strings", 60, 90).attack).toBeGreaterThan(voicePlan("grand", 60, 90).attack * 10);
  });

  it("drops partials that would be above the audible range", () => {
    const high = voicePlan("grand", 108, 100);
    for (const o of high.oscillators) expect(o.frequency).toBeLessThan(18000);
    expect(high.oscillators.length).toBeLessThan(8);
  });

  it("uses frequency modulation for the electric piano only", () => {
    expect(voicePlan("electric", 60, 90).fm).not.toBeNull();
    for (const id of SOUND_IDS.filter((s) => s !== "electric")) expect(voicePlan(id, 60, 90).fm).toBeNull();
  });

  it("has finite, positive envelope values for every sound and key", () => {
    for (const id of SOUND_IDS)
      for (let midi = 21; midi <= 108; midi++) {
        const p = voicePlan(id, midi, 90);
        for (const v of [p.attack, p.peak, p.release]) expect(Number.isFinite(v) && v > 0).toBe(true);
        for (const o of p.oscillators) expect(Number.isFinite(o.frequency) && o.frequency > 0).toBe(true);
      }
  });
});

describe("layers", () => {
  it("makes one voice plan per active layer and skips silent ones", () => {
    const plans = planLayers([{ sound: "grand", gain: 1 }, { sound: "strings", gain: 0 }, { sound: "bells", gain: 0.5 }], 60, 90);
    expect(plans).toHaveLength(2);
  });

  it("does not get louder as layers are added", () => {
    const level = (layers: Parameters<typeof planLayers>[0]) =>
      planLayers(layers, 60, 100).reduce((s, p) => s + p.peak * p.oscillators.reduce((a, o) => a + o.gain, 0), 0);
    const one = level([{ sound: "grand", gain: 1 }]);
    const three = level([
      { sound: "grand", gain: 1 },
      { sound: "strings", gain: 1 },
      { sound: "bells", gain: 1 },
    ]);
    expect(three).toBeLessThan(one * 1.6);
  });

  it("has nothing to play with no layers", () => {
    expect(planLayers([], 60, 90)).toEqual([]);
  });
});
