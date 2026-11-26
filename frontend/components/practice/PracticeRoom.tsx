"use client";

import { Pause, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PianoKeyboard } from "@/components/piano/PianoKeyboard";
import { prettyNote, selectClass } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type Built, LEVELS, type Level, type MovementSummary, type Step, getMovement, listMovements } from "@/lib/movements/api";
import { BOTH_HANDS, type Hands as HandFlags, centreMidi, overlayFromStep, stepAtBeat, stepEvent } from "@/lib/movements/playback";
import { type Playback, PianoAudio } from "@/lib/piano/audio";
import { WHITE_COUNT, keyFor } from "@/lib/piano/keys";
import { connectMidi } from "@/lib/piano/midiInput";
import { DEFAULT_PREFS, type Prefs, loadPrefs } from "@/lib/piano/prefs";
import {
  ClickScheduler, createClicker,
} from "@/lib/practice/metronome";
import {
  type PracticePlan, type Position, allClicks, defaultPlan, loopFromSteps, notesForPass, passCount, planProblems, planSeconds, positionAt, scoringParams, timeline,
} from "@/lib/practice/clock";
import { type Hands, WINDOW_BY_LEVEL, scorePass } from "@/lib/practice/api";
import { Recorder, reportedLatencyMs } from "@/lib/practice/recorder";
import { type WaitState, askedSteps, pressNote, startWait } from "@/lib/practice/wait";
import { saveWaitResult } from "@/lib/practice/api";
import { useStickyScrollPadding } from "@/lib/useStickyScrollPadding";
import { PracticeHistory } from "./PracticeHistory";
import { type PassScore, ScoreView } from "./ScoreView";

type Mode = "play" | "wait" | "history";
const MODES: { id: Mode; label: string }[] = [
  { id: "play", label: "Play along" },
  { id: "wait", label: "Wait for me" },
  { id: "history", label: "My progress" },
];
const TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const HAND_FLAGS: Record<Hands, HandFlags> = { both: BOTH_HANDS, L: { L: true, R: false }, R: { L: false, R: true } };
const HAND_LABEL: Record<Hands, string> = { both: "Both hands", L: "Left hand", R: "Right hand" };
const card = "rounded-xl border border-line bg-surface p-5";
const field = "min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent";
const num = (v: string, lo: number, hi: number, fallback: number): number => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : fallback;
};

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

const uuid = (): string => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : "00000000-0000-4000-8000-000000000000".replace(/0/g, () => ((Math.random() * 16) | 0).toString(16)));
const expectedFor = (s: Step, h: HandFlags): number[] => [...new Set([...(h.L ? s.left : []), ...(h.R ? s.right : [])])];
const otherHands = (h: Hands): HandFlags => (h === "both" ? { L: false, R: false } : h === "L" ? { L: false, R: true } : { L: true, R: false });

type Run = { sched: ClickScheduler; recorder: Recorder; plan: PracticePlan; role: "play" | "listen"; playbacks: Playback[]; ui: number; sessionId: string; hands: Hands; level: Level; slug: string; key: string | undefined; window: number; latency: number; octave: boolean; save: boolean };

export function PracticeRoom() {
  const [list, setList] = useState<MovementSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [slug, setSlug] = useState("");
  const [tonic, setTonic] = useState<string>("");
  const [movement, setMovement] = useState<Built | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("play");
  const [level, setLevel] = useState<Level>("intermediate");

  // what the player does
  const [mine, setMine] = useState<Hands>("both");
  const [role, setRole] = useState<"play" | "listen">("play");
  const [hearOther, setHearOther] = useState(true);
  const [showNotes, setShowNotes] = useState(true);
  const [octave, setOctave] = useState(false);
  // the practice plan
  const [percent, setPercent] = useState(100);
  const [countBars, setCountBars] = useState(1);
  const [countEach, setCountEach] = useState(false);
  const [metronome, setMetronome] = useState(true);
  const [metVolume, setMetVolume] = useState(0.6);
  const [loopOn, setLoopOn] = useState(false);
  const [loopFrom, setLoopFrom] = useState(0);
  const [loopTo, setLoopTo] = useState(0);
  const [passes, setPasses] = useState(4);
  const [rampOn, setRampOn] = useState(false);
  const [ramp, setRamp] = useState({ start: 60, step: 10, every: 2, target: 100 });
  // scoring
  const [windowLevel, setWindowLevel] = useState<Level>("intermediate");
  const [latency, setLatency] = useState(0);
  const [latencyTouched, setLatencyTouched] = useState(false);
  const [saveResults, setSaveResults] = useState(true);

  // run state
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState<Position | null>(null);
  const [results, setResults] = useState<PassScore[] | null>(null);
  const [scoring, setScoring] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [audioProblem, setAudioProblem] = useState<string | null>(null);
  const [savedCount, setSavedCount] = useState(0);
  // wait mode
  const [wait, setWait] = useState<WaitState | null>(null);
  const waitSession = useRef(uuid());
  const waitSaved = useRef(false);
  // keyboard
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [held, setHeld] = useState<ReadonlySet<number>>(new Set());
  const [midiText, setMidiText] = useState<string | null>(null);

  const audioRef = useRef<PianoAudio | null>(null);
  const midiOff = useRef<(() => void) | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const run = useRef<Run | null>(null);
  const audio = useCallback(() => (audioRef.current ??= new PianoAudio()), []);

  useEffect(() => setPrefs(loadPrefs(window.localStorage)), []);
  useEffect(() => { audio().setVolume(prefs.volume); audio().setTuning(prefs.a4); }, [audio, prefs.volume, prefs.a4]);

  // ---- movements
  useEffect(() => {
    void listMovements({}).then((r) => {
      if (!r.ok) return setListError(failureText(r));
      setList(r.data.items);
      setSlug((s) => s || r.data.items[0]?.slug || "");
    });
  }, []);
  useEffect(() => {
    if (!slug) return;
    let off = false;
    setLoadError(null);
    void getMovement(slug, tonic || undefined).then((r) => {
      if (off) return;
      if (r.ok) setMovement(r.data.movement); else { setMovement(null); setLoadError(failureText(r)); }
    });
    return () => { off = true; };
  }, [slug, tonic]);

  const version = useMemo(() => movement?.versions.find((v) => v.level === level) ?? movement?.versions[0] ?? null, [movement, level]);
  useEffect(() => {
    if (movement && !movement.versions.some((v) => v.level === level)) setLevel(movement.versions[0]?.level ?? "beginner");
  }, [movement, level]);
  useEffect(() => {
    setLoopFrom(0);
    setLoopTo(Math.max(0, (version?.steps.length ?? 1) - 1));
  }, [version?.level, movement?.slug]);

  // ---- the plan
  const plan: PracticePlan | null = useMemo(() => {
    if (!movement || !version) return null;
    const beatsPerBar = Math.max(1, Math.round(version.time_signature[0] ?? 4));
    const loop = loopOn ? loopFromSteps(version.steps, loopFrom, loopTo, version.total_beats) : null;
    return defaultPlan(
      { tempo: movement.tempo, time_signature: version.time_signature, total_beats: version.total_beats },
      {
        percent, countInBeats: countBars * beatsPerBar, countInEachPass: countEach, loop,
        passes: loop ? passes : null,
        ramp: loop && rampOn ? { startPercent: ramp.start, stepPercent: ramp.step, everyPasses: ramp.every, targetPercent: ramp.target } : null,
      },
    );
  }, [movement, version, percent, countBars, countEach, loopOn, loopFrom, loopTo, passes, rampOn, ramp]);
  const problems = plan ? planProblems(plan) : [];

  const live = useRef({ metronome, metVolume, layers: prefs.layers });
  live.current = { metronome, metVolume, layers: prefs.layers };

  // ---- stopping and scoring
  const finish = useCallback(async () => {
    const r = run.current;
    if (!r) return;
    const sec = r.sched.sessionSeconds() ?? Number.POSITIVE_INFINITY; // null after the plan ended by itself
    r.sched.stop();
    for (const p of r.playbacks) p.stop();
    audioRef.current?.allNotesOff();
    window.clearInterval(r.ui);
    run.current = null;
    setPlaying(false);
    setPos(null);
    if (r.role !== "play") return;
    const played = r.recorder.notes();
    if (played.length === 0) return setNotice("No notes were played, so nothing was scored.");
    const done = timeline(r.plan).filter((p) => p.endSeconds <= sec + 0.05).slice(0, 30);
    if (done.length === 0) return setNotice("You stopped before a pass finished. Only finished passes are scored.");
    setScoring(true);
    const out = await Promise.all(
      done.map(async (p): Promise<PassScore> => {
        const sp = scoringParams(r.plan, p.index);
        const res = await scorePass({
          movement: { slug: r.slug, level: r.level, key: r.key, hands: r.hands },
          played: r.recorder.between(p.startSeconds - 0.5, p.endSeconds + 0.5),
          tempo_bpm: sp.tempo_bpm, offset_s: sp.offset_s, window_ms: r.window, latency_ms: r.latency, octave_equivalent: r.octave,
          ...(sp.beat_range ? { beat_range: sp.beat_range } : {}),
          ...(r.save ? { save: { session_id: r.sessionId, pass_index: p.index } } : {}),
        });
        return res.ok ? { pass: p.index, tempo: p.tempo, score: res.data, error: null } : { pass: p.index, tempo: p.tempo, score: null, error: failureText(res) };
      }),
    );
    setScoring(false);
    setResults(out);
    if (out.some((o) => o.score?.saved_id)) setSavedCount((n) => n + 1);
  }, []);

  const stopNow = useCallback(() => void finish(), [finish]);
  useEffect(() => () => {
    const r = run.current;
    if (r) { r.sched.stop(); for (const p of r.playbacks) p.stop(); window.clearInterval(r.ui); run.current = null; }
    audioRef.current?.allNotesOff();
    midiOff.current?.();
  }, []);
  useEffect(() => { if (run.current) void finish(); }, [mode, slug, tonic, level, finish]); // changing the piece or mode ends a run

  const start = async () => {
    if (!plan || !version || !movement || problems.length) return;
    const a = audio();
    if (!(await a.resume()) || !a.context) return setAudioProblem("This browser could not start sound, so practice cannot run here.");
    setAudioProblem(null); setNotice(null); setResults(null);
    if (run.current) await finish();
    const ctx = a.context;
    if (!latencyTouched) setLatency(reportedLatencyMs(ctx));
    const clicker = createClicker(ctx, () => (live.current.metronome ? live.current.metVolume : 0));
    const sched = new ClickScheduler({ now: () => ctx.currentTime, play: clicker, setTimer: (fn, ms) => window.setTimeout(fn, ms), clearTimer: (id) => window.clearTimeout(id as number) });
    const computer: HandFlags = role === "listen" ? BOTH_HANDS : hearOther ? otherHands(mine) : { L: false, R: false };
    const total = passCount(plan);
    const playbacks: Playback[] = [];
    let scheduled = -1;
    const scheduleThrough = (pass: number) => {
      while (scheduled < Math.min(pass, total - 1)) {
        scheduled += 1;
        playbacks.push(a.scheduleAt(sched.startedAt ?? ctx.currentTime, notesForPass(plan, scheduled, version.playback, computer), live.current.layers));
      }
    };
    const r: Run = { sched, recorder: new Recorder(), plan, role, playbacks, ui: 0, sessionId: uuid(), hands: mine, level: version.level, slug: movement.slug, key: tonic || undefined, window: WINDOW_BY_LEVEL[windowLevel], latency, octave, save: saveResults };
    run.current = r;
    sched.start(allClicks(plan), { endSeconds: planSeconds(plan), onClick: (c) => scheduleThrough(c.pass + 1), onEnd: () => void finish() });
    scheduleThrough(1);
    r.ui = window.setInterval(() => {
      const sec = sched.sessionSeconds();
      if (sec !== null) setPos(positionAt(plan, sec));
    }, 60);
    setPlaying(true);
  };

  // ---- notes from the keys or a MIDI keyboard
  const noteEvent = useCallback((midi: number, on: boolean) => {
    const r = run.current;
    const ctx = audioRef.current?.context;
    if (r && r.role === "play" && ctx && r.sched.startedAt !== null) {
      const t = ctx.currentTime - r.sched.startedAt;
      if (on) r.recorder.noteOn(midi, t); else r.recorder.noteOff(midi, t);
    }
  }, []);
  const waitPlan = useMemo(() => (version ? version.steps.map((s) => expectedFor(s, HAND_FLAGS[mine])) : []), [version, mine]);
  useEffect(() => { setWait(waitPlan.length ? startWait(waitPlan) : null); waitSession.current = uuid(); waitSaved.current = false; }, [waitPlan, octave, mode]);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const waitRef = useRef({ waitPlan, octave });
  waitRef.current = { waitPlan, octave };

  const keyDown = useCallback((n: number, v: number) => {
    void audio().resume().then(() => audio().noteOn(n, v, live.current.layers));
    setHeld((h) => new Set(h).add(n));
    noteEvent(n, true);
    if (modeRef.current === "wait") setWait((w) => (w ? pressNote(w, waitRef.current.waitPlan, n, waitRef.current.octave) : w));
  }, [audio, noteEvent]);
  const keyUp = useCallback((n: number) => {
    audio().noteOff(n);
    setHeld((h) => { const next = new Set(h); next.delete(n); return next; });
    noteEvent(n, false);
  }, [audio, noteEvent]);

  const connectKeyboard = async () => {
    midiOff.current?.();
    midiOff.current = await connectMidi({
      onStatus: (s) => setMidiText(s.state === "ready" ? (s.devices.length ? `Listening to ${s.devices.join(", ")}.` : "No MIDI keyboard found.") : s.state === "denied" ? "MIDI access was blocked." : "This browser does not support MIDI keyboards."),
      onMessage: (m) => { if (m.type === "on") keyDown(m.note, m.velocity); else if (m.type === "off") keyUp(m.note); else if (m.type === "sustain") audio().setSustain(m.on); },
    });
  };

  // wait mode: keep the finished result
  useEffect(() => {
    if (!wait?.done || waitSaved.current || !movement || !version || mode !== "wait") return;
    waitSaved.current = true;
    if (!saveResults) return;
    void saveWaitResult({ movement_slug: movement.slug, level: version.level, ...(tonic ? { key: tonic } : {}), hands: mine, session_id: waitSession.current, steps: askedSteps(waitPlan), first_try: wait.firstTry, wrong_presses: wait.wrongTotal }).then((r) => r.ok && setSavedCount((n) => n + 1));
  }, [wait?.done, wait, movement, version, mode, saveResults, tonic, mine, waitPlan]);

  // ---- what the keyboard shows
  const shownStep: Step | undefined = useMemo(() => {
    if (!version) return undefined;
    if (mode === "wait" && wait) return version.steps[Math.min(wait.index, version.steps.length - 1)];
    if (pos && !pos.inCountIn) return version.steps[stepAtBeat(version, pos.beat)];
    return version.steps[0];
  }, [version, mode, wait, pos]);
  const overlay = useMemo(() => (showNotes && shownStep ? overlayFromStep(shownStep, role === "listen" && mode === "play" ? BOTH_HANDS : HAND_FLAGS[mine]) : null), [showNotes, shownStep, role, mine, mode]);
  useEffect(() => {
    const el = scrollRef.current;
    const mid = shownStep ? centreMidi(shownStep) : null;
    const k = mid === null ? undefined : keyFor(mid);
    if (el && k) el.scrollLeft = Math.max(0, (k.x + 0.5) * prefs.keyWidth - el.clientWidth / 2);
  }, [shownStep, prefs.keyWidth]);
  useStickyScrollPadding(stageRef, Boolean(movement && version && mode !== "history"));

  const hear = async (s: Step | undefined) => {
    if (!s || !(await audio().resume())) return;
    audio().schedule(stepEvent(s, HAND_FLAGS[mine]), 120, prefs.layers);
  };

  if (listError) return <Notice tone="error">{listError}</Notice>;
  if (!list) return <p className="text-sm text-muted" aria-busy="true">Loading movements…</p>;
  if (list.length === 0) return <Notice>No chord movements are published yet, so there is nothing to practise.</Notice>;

  const steps = version?.steps ?? [];
  const tempoNow = pos?.tempo ?? (plan ? Math.round(plan.baseTempo * percent) / 100 : 0);

  return (
    <div className="space-y-6">
      <section aria-label="Choose what to practise" className={`${card} grid gap-4 sm:grid-cols-2 lg:grid-cols-4`}>
        <Field label="Chord movement">
          <select className={`${selectClass} min-h-11`} value={slug} onChange={(e) => setSlug(e.target.value)}>
            {list.map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}
          </select>
        </Field>
        <Field label="Level">
          <select className={`${selectClass} min-h-11`} value={version?.level ?? level} onChange={(e) => setLevel(e.target.value as Level)}>
            {LEVELS.filter((l) => movement?.versions.some((v) => v.level === l)).map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </Field>
        <Field label="Key">
          <select className={`${selectClass} min-h-11`} value={tonic} onChange={(e) => setTonic(e.target.value)}>
            <option value="">Original ({movement?.key.tonic ?? "…"})</option>
            {TONICS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="You play">
          <select className={`${selectClass} min-h-11`} value={mine} onChange={(e) => setMine(e.target.value as Hands)}>
            {(Object.keys(HAND_LABEL) as Hands[]).map((h) => <option key={h} value={h}>{HAND_LABEL[h]}</option>)}
          </select>
        </Field>
      </section>
      {loadError ? <Notice tone="error">{loadError}</Notice> : null}

      <div role="tablist" aria-label="Practice mode" className="flex flex-wrap gap-2">
        {MODES.map((m) => (
          <button key={m.id} type="button" role="tab" aria-selected={mode === m.id} onClick={() => setMode(m.id)}
            className={`min-h-11 rounded-lg border px-4 text-sm font-medium ${mode === m.id ? "border-accent bg-accent-soft" : "border-line"}`}>{m.label}</button>
        ))}
      </div>

      {mode !== "history" && movement && version ? (
        <div ref={stageRef} className="sticky top-[3.6rem] z-10 lg:top-2 [@media(max-height:620px)]:static">
          <div className="rounded-xl border border-line bg-surface p-3 shadow-md">
            <div className="mb-2.5 min-h-9 text-sm" aria-live="polite">
              {mode === "play" && pos?.inCountIn ? <span className="text-2xl font-extrabold">{pos.countInBeat}</span>
                : shownStep ? <span><span className="text-muted">{mode === "wait" ? "Play " : playing ? "Now " : "Showing "}</span><span className="font-semibold">{prettyNote(shownStep.roman ? `${shownStep.symbol} (${shownStep.roman})` : shownStep.symbol)}</span>
                  {mode === "play" && pos ? <span className="text-muted"> · pass {pos.pass + 1}{plan && plan.loop && plan.passes ? ` of ${plan.passes}` : ""} · {pos.tempo} BPM</span> : null}</span> : null}
            </div>
            <PianoKeyboard keyWidth={prefs.keyWidth} held={held} overlay={overlay}
              labels={{ mode: prefs.labels, accidentals: prefs.accidentals, middleC: prefs.middleC, unicode: prefs.unicode }}
              scrollRef={scrollRef} onKeyDown={keyDown} onKeyUp={keyUp} />
            <div className="mt-2.5 flex flex-wrap items-center gap-3">
              <button type="button" onClick={() => void connectKeyboard()} className={buttonStyles({ variant: "secondary" })}>Use a MIDI keyboard</button>
              {midiText ? <span className="text-xs text-muted">{midiText}</span> : <span className="text-xs text-muted">Play the on-screen keys, your computer keyboard, or a MIDI keyboard.</span>}
              <label className="ml-auto flex items-center gap-2 text-sm"><input type="checkbox" checked={showNotes} onChange={(e) => setShowNotes(e.target.checked)} /> Show the notes on the keys</label>
            </div>
          </div>
        </div>
      ) : null}
      {audioProblem ? <Notice tone="error">{audioProblem}</Notice> : null}

      {mode === "play" && plan && version ? (
        <>
          <section aria-label="Practice settings" className={`${card} space-y-5`}>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label={`Speed: ${percent}% (${Math.round(plan.baseTempo * percent) / 100} BPM)`}>
                <input type="range" min={25} max={150} step={5} value={percent} onChange={(e) => setPercent(Number(e.target.value))} className="w-full" disabled={rampOn && loopOn} />
              </Field>
              <Field label="Count-in">
                <select className={`${selectClass} min-h-11`} value={countBars} onChange={(e) => setCountBars(Number(e.target.value))}>
                  <option value={0}>None</option><option value={1}>1 bar</option><option value={2}>2 bars</option>
                </select>
              </Field>
              <Field label="You">
                <select className={`${selectClass} min-h-11`} value={role} onChange={(e) => setRole(e.target.value as "play" | "listen")}>
                  <option value="play">Play (recorded and scored)</option><option value="listen">Listen first (both hands play)</option>
                </select>
              </Field>
              <Field label="Metronome">
                <span className="flex min-h-11 items-center gap-3">
                  <input type="checkbox" checked={metronome} onChange={(e) => setMetronome(e.target.checked)} aria-label="Metronome on" />
                  <input type="range" min={0.1} max={1} step={0.1} value={metVolume} onChange={(e) => setMetVolume(Number(e.target.value))} className="w-full" aria-label="Metronome volume" />
                </span>
              </Field>
            </div>
            <div className="space-y-3">
              <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={loopOn} onChange={(e) => setLoopOn(e.target.checked)} /> Loop a section</label>
              {loopOn ? (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label="From chord"><select className={`${selectClass} min-h-11`} value={loopFrom} onChange={(e) => setLoopFrom(Number(e.target.value))}>{steps.map((s, i) => <option key={s.index} value={i}>{i + 1}. {prettyNote(s.symbol)}</option>)}</select></Field>
                  <Field label="To chord"><select className={`${selectClass} min-h-11`} value={loopTo} onChange={(e) => setLoopTo(Number(e.target.value))}>{steps.map((s, i) => <option key={s.index} value={i}>{i + 1}. {prettyNote(s.symbol)}</option>)}</select></Field>
                  <Field label="Passes (1 to 500)"><input className={field} inputMode="numeric" value={passes} onChange={(e) => setPasses(Math.round(num(e.target.value, 1, 500, 4)))} /></Field>
                  <Field label="Count-in"><label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={countEach} onChange={(e) => setCountEach(e.target.checked)} /> before every pass</label></Field>
                </div>
              ) : null}
              {loopOn ? (
                <div className="space-y-3">
                  <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={rampOn} onChange={(e) => setRampOn(e.target.checked)} /> Speed trainer: start slow and speed up</label>
                  {rampOn ? (
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                      <Field label="Start at (%)"><input className={field} inputMode="numeric" value={ramp.start} onChange={(e) => setRamp({ ...ramp, start: num(e.target.value, 10, 200, 60) })} /></Field>
                      <Field label="Add (%)"><input className={field} inputMode="numeric" value={ramp.step} onChange={(e) => setRamp({ ...ramp, step: num(e.target.value, 1, 100, 10) })} /></Field>
                      <Field label="After every (passes)"><input className={field} inputMode="numeric" value={ramp.every} onChange={(e) => setRamp({ ...ramp, every: Math.round(num(e.target.value, 1, 50, 2)) })} /></Field>
                      <Field label="Up to (%)"><input className={field} inputMode="numeric" value={ramp.target} onChange={(e) => setRamp({ ...ramp, target: num(e.target.value, 10, 200, 100) })} /></Field>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
            <details className="text-sm">
              <summary className="cursor-pointer font-medium">Scoring settings</summary>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="How strict" hint={`Timing window: ${WINDOW_BY_LEVEL[windowLevel]} ms either side`}>
                  <select className={`${selectClass} min-h-11`} value={windowLevel} onChange={(e) => setWindowLevel(e.target.value as Level)}>{LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}</select>
                </Field>
                <Field label="Sound delay to remove (ms)" hint="Set automatically from the browser when it can tell. Raise it if you always seem to play late.">
                  <input className={field} inputMode="numeric" value={latency} onChange={(e) => { setLatencyTouched(true); setLatency(Math.round(num(e.target.value, 0, 500, 0))); }} />
                </Field>
                <Field label="Octave"><label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={octave} onChange={(e) => setOctave(e.target.checked)} /> Any octave is fine</label></Field>
                <Field label="History"><label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={saveResults} onChange={(e) => setSaveResults(e.target.checked)} /> Save results</label></Field>
              </div>
            </details>
            {problems.length ? <Notice tone="error">{problems.join(" ")}</Notice> : null}
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" disabled={problems.length > 0 || scoring} onClick={() => (playing ? stopNow() : void start())} className={buttonStyles({ variant: "primary" })}>
                {playing ? <Pause aria-hidden className="h-4 w-4" /> : <Play aria-hidden className="h-4 w-4" />} {playing ? "Stop" : role === "listen" ? "Listen" : "Start"}
              </button>
              {role === "play" ? (
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={hearOther} onChange={(e) => setHearOther(e.target.checked)} /> Play the hand I am not playing</label>
              ) : null}
              <span className="text-sm text-muted">{playing ? `${tempoNow} BPM` : "Only finished passes are scored."}</span>
            </div>
          </section>
          {notice ? <Notice>{notice}</Notice> : null}
          {scoring ? <p className="text-sm text-muted" aria-busy="true">Scoring…</p> : null}
          {results ? <ScoreView passes={results} /> : null}
        </>
      ) : null}

      {mode === "wait" && version && wait ? (
        <section aria-label="Wait mode" className={`${card} space-y-4`}>
          <p className="text-sm text-muted">The music waits for you. Play every note of the chord shown; any wrong note is counted, then the next chord is asked for.</p>
          {wait.done ? (
            <div className="space-y-2" data-testid="wait-summary">
              <p className="text-2xl font-extrabold tracking-tight">{askedSteps(waitPlan) ? Math.round((wait.firstTry / askedSteps(waitPlan)) * 100) : 0}% <span className="text-sm font-normal text-muted">{wait.firstTry} of {askedSteps(waitPlan)} chords first time, {wait.wrongTotal} wrong {wait.wrongTotal === 1 ? "note" : "notes"}</span></p>
              <button type="button" className={buttonStyles({ variant: "primary" })} onClick={() => { waitSession.current = uuid(); waitSaved.current = false; setWait(startWait(waitPlan)); }}>Go again</button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span>Chord {wait.index + 1} of {steps.length}</span>
              <span className="text-muted">· got {wait.got.length} of {waitPlan[wait.index]?.length ?? 0} notes · {wait.wrongNow} wrong on this chord</span>
              <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => void hear(shownStep)}>Hear this chord</button>
              <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => setWait(startWait(waitPlan))}>Start again</button>
            </div>
          )}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={octave} onChange={(e) => setOctave(e.target.checked)} /> Any octave is fine</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={saveResults} onChange={(e) => setSaveResults(e.target.checked)} /> Save the result</label>
        </section>
      ) : null}

      {mode === "history" ? <PracticeHistory slug={undefined} refreshKey={savedCount} /> : null}
    </div>
  );
}
