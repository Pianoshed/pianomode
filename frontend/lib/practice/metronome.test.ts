import { describe, expect, it } from "vitest";
import { type Click, allClicks, defaultPlan, planSeconds } from "./clock";
import { CLICK_PITCH, ClickScheduler, type SchedulerDeps, clickSound, createClicker } from "./metronome";

/** A fake audio clock and timer queue. `advance` runs timers in time order. */
function harness(extra: Partial<SchedulerDeps> = {}) {
  let time = 0;
  let nextId = 0;
  const timers = new Map<number, { fn: () => void; at: number }>();
  const played: { at: number; click: Click; heardAt: number }[] = [];
  const deps: SchedulerDeps = {
    now: () => time,
    play: (at, click) => played.push({ at, click, heardAt: time }),
    setTimer: (fn, ms) => {
      nextId += 1;
      timers.set(nextId, { fn, at: time + ms / 1000 });
      return nextId;
    },
    clearTimer: (id) => void timers.delete(id as number),
    ...extra,
  };
  const advance = (seconds: number) => {
    const target = time + seconds;
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= target + 1e-12).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      time = Math.max(time, due[1].at);
      due[1].fn();
    }
    time = target;
  };
  return { deps, played, advance, timers, setTime: (t: number) => (time = t) };
}

// 4 beats at 120 BPM, no count-in: clicks at session seconds 0, 0.5, 1, 1.5.
const plan = () => defaultPlan({ tempo: 120, time_signature: [4, 4], total_beats: 4 }, { countInBeats: 0 });

describe("ClickScheduler", () => {
  it("hands each click to the audio clock early, at its exact time", () => {
    const h = harness();
    const s = new ClickScheduler(h.deps);
    s.start(allClicks(plan()));
    h.advance(2.5);
    expect(h.played.map((p) => p.at)).toEqual([0.05, 0.55, 1.05, 1.55]);
    for (const p of h.played) {
      expect(p.at).toBeGreaterThanOrEqual(p.heardAt); // never handed over late
      expect(p.at - p.heardAt).toBeLessThanOrEqual(0.2 + 1e-9); // and never further ahead than the lookahead
    }
    expect(h.played.map((p) => p.click.beat)).toEqual([0, 1, 2, 3]);
  });

  it("plays the first click straight away, after the start delay", () => {
    const h = harness();
    new ClickScheduler(h.deps).start(allClicks(plan()));
    expect(h.played).toHaveLength(1);
    expect(h.played[0]!.at).toBeCloseTo(0.05, 9);
  });

  it("reports the session clock", () => {
    const h = harness();
    const s = new ClickScheduler(h.deps);
    expect(s.sessionSeconds()).toBeNull();
    s.start(allClicks(plan()));
    expect(s.startedAt).toBeCloseTo(0.05, 9);
    h.advance(1.05);
    expect(s.sessionSeconds()).toBeCloseTo(1, 9);
  });

  it("calls onEnd once at the end of the plan, then stops", () => {
    const h = harness();
    const s = new ClickScheduler(h.deps);
    let ended = 0;
    const clicks: number[] = [];
    s.start(allClicks(plan()), { endSeconds: planSeconds(plan()), onEnd: () => (ended += 1), onClick: (c) => clicks.push(c.beat) });
    h.advance(1.9);
    expect(ended).toBe(0);
    expect(s.running).toBe(true);
    h.advance(0.5);
    expect(ended).toBe(1);
    expect(s.running).toBe(false);
    expect(h.timers.size).toBe(0);
    expect(clicks).toEqual([0, 1, 2, 3]);
    h.advance(5);
    expect(ended).toBe(1);
  });

  it("stop() cancels everything that has not been handed over", () => {
    const h = harness();
    const s = new ClickScheduler(h.deps);
    s.start(allClicks(plan()));
    h.advance(0.6);
    s.stop();
    const count = h.played.length;
    h.advance(5);
    expect(h.played).toHaveLength(count);
    expect(s.running).toBe(false);
    expect(s.sessionSeconds()).toBeNull();
    expect(h.timers.size).toBe(0);
  });

  it("starting again restarts from second 0 without doubling the timers", () => {
    const h = harness();
    const s = new ClickScheduler(h.deps);
    s.start(allClicks(plan()));
    h.advance(1);
    const before = h.played.length; // clicks the first run had already handed over still sound
    s.start(allClicks(plan()));
    expect(h.timers.size).toBe(1);
    expect(s.startedAt).toBeCloseTo(1.05, 9);
    h.advance(0.6);
    const second = h.played.slice(before);
    expect(second.map((p) => p.click.beat)).toEqual([0, 1]);
    expect(second.map((p) => p.at)).toEqual([1.05, 1.55]);
  });

  it("drops clicks it was too late to play instead of bunching them up", () => {
    const h = harness();
    const s = new ClickScheduler(h.deps);
    s.start(allClicks(plan())); // click 0 at 0.05 is handed over
    h.setTime(1.0); // the page was frozen for a second; no timer ran
    for (const t of [...h.timers.values()]) t.fn();
    expect(s.droppedClicks).toBe(1); // the click due at 0.55 is long gone
    expect(h.played.map((p) => p.at)).toEqual([0.05, 1.05]);
  });

  it("without an end time, ends once the last click has been handed over", () => {
    const h = harness();
    const s = new ClickScheduler(h.deps);
    let ended = 0;
    s.start(allClicks(plan()), { onEnd: () => (ended += 1) });
    h.advance(1.5);
    expect(ended).toBe(1);
    expect(h.played).toHaveLength(4);
  });

  it("keeps up with a loop that has no end", () => {
    const loop = defaultPlan({ tempo: 120, time_signature: [4, 4], total_beats: 16 }, { loop: { startBeat: 0, endBeat: 4 }, passes: null, countInBeats: 0 });
    const h = harness();
    new ClickScheduler(h.deps).start(allClicks(loop));
    h.advance(10);
    expect(h.played.length).toBeGreaterThanOrEqual(20);
    expect(h.played.map((p) => p.at)).toEqual([...h.played.map((p) => p.at)].sort((a, b) => a - b));
  });

  it("clicks the count-in at its own pitch before the music", () => {
    const withCount = defaultPlan({ tempo: 120, time_signature: [4, 4], total_beats: 4 });
    const h = harness();
    new ClickScheduler(h.deps).start(allClicks(withCount));
    h.advance(5);
    expect(h.played.slice(0, 4).every((p) => p.click.countIn)).toBe(true);
    expect(h.played.slice(4).every((p) => !p.click.countIn)).toBe(true);
    expect(h.played[4]!.at).toBeCloseTo(2.05, 9);
  });
});

describe("click sound", () => {
  it("accents bar lines and sets the count-in apart", () => {
    expect(clickSound({ accent: true, countIn: false }, 1)).toEqual({ frequency: CLICK_PITCH.accent, gain: 1 });
    expect(clickSound({ accent: false, countIn: false }, 1)).toEqual({ frequency: CLICK_PITCH.beat, gain: 0.6 });
    expect(clickSound({ accent: true, countIn: true }, 0.5).frequency).toBe(CLICK_PITCH.countIn);
    expect(clickSound({ accent: false, countIn: false }, 5).gain).toBeCloseTo(0.6, 9); // volume is capped at 1
    expect(clickSound({ accent: false, countIn: false }, -1).gain).toBe(0);
  });

  it("builds a short blip at the exact time", () => {
    const calls: string[] = [];
    const param = (name: string) => ({
      setValueAtTime: (v: number, t: number) => calls.push(`${name}.set ${v} @${t}`),
      exponentialRampToValueAtTime: (v: number, t: number) => calls.push(`${name}.ramp ${v} @${t}`),
    });
    const node = (name: string) => {
      const n: Record<string, unknown> = { connect: (x: unknown) => x };
      n.frequency = param(`${name}.frequency`);
      n.gain = param(`${name}.gain`);
      n.start = (t: number) => calls.push(`${name}.start @${t}`);
      n.stop = (t: number) => calls.push(`${name}.stop @${t}`);
      return n;
    };
    const ctx = { destination: {}, createOscillator: () => node("osc"), createGain: () => node("env") } as unknown as AudioContext;
    createClicker(ctx, () => 1)(2, { time: 0, beat: 0, accent: true, countIn: false, pass: 0 });
    expect(calls).toContain(`osc.frequency.set ${CLICK_PITCH.accent} @2`);
    expect(calls).toContain("osc.start @2");
    expect(calls).toContain("osc.stop @2.06");
    expect(calls).toContain("env.gain.ramp 1 @2.002");
  });

  it("makes no sound at zero volume", () => {
    let made = 0;
    const ctx = { destination: {}, createOscillator: () => (made += 1), createGain: () => (made += 1) } as unknown as AudioContext;
    createClicker(ctx, () => 0)(1, { time: 0, beat: 0, accent: false, countIn: false, pass: 0 });
    expect(made).toBe(0);
  });
});
