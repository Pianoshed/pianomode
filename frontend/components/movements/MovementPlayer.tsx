"use client";

import { Pause, Play, Repeat } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SaveToLibrary } from "@/components/library/SaveToLibrary";
import { type ProgressionSettings, serializeProgression } from "@/lib/library/progression";
import { Notice } from "@/components/ui/Notice";
import { Skeleton } from "@/components/ui/Skeleton";
import { buttonStyles } from "@/components/ui/button";
import { PianoKeyboard } from "@/components/piano/PianoKeyboard";
import { prettyNote } from "@/components/piano/shared";
import { type ApiResult, failureText } from "@/lib/api";
import {
  type Built,
  LEVELS,
  LEVEL_INFO,
  type Level,
  type MovementDetail,
  type Step,
  type Version,
  adminPreview,
  getMovement,
} from "@/lib/movements/api";
import {
  BOTH_HANDS,
  type Hands,
  beatSeconds,
  centreMidi,
  eventsFrom,
  overlayFromStep,
  resumeBeat,
  stepAtBeat,
  stepEvent,
} from "@/lib/movements/playback";
import { type Playback, PianoAudio } from "@/lib/piano/audio";
import { WHITE_COUNT, keyFor } from "@/lib/piano/keys";
import { DEFAULT_PREFS, type Prefs, STORAGE_KEY, loadPrefs } from "@/lib/piano/prefs";
import { useStickyScrollPadding } from "@/lib/useStickyScrollPadding";

type HandMode = "both" | "L" | "R";
const HANDS: Record<HandMode, Hands> = { both: BOTH_HANDS, L: { L: true, R: false }, R: { L: false, R: true } };
const HAND_LABEL: Record<HandMode, string> = { both: "Both hands", L: "Left hand only", R: "Right hand only" };

type Source = { slug: string; previewId?: undefined } | { previewId: string; slug?: undefined };

function useMovement(source: Source, tonic: string | null) {
  const [state, setState] = useState<{ detail: MovementDetail | null; error: string | null; loading: boolean }>({
    detail: null,
    error: null,
    loading: true,
  });
  const id = source.slug ?? source.previewId;
  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    const request: Promise<ApiResult<MovementDetail>> = source.previewId
      ? adminPreview(source.previewId).then((r) =>
          r.ok ? { ok: true as const, data: { movement: r.data.movement, live: true, score_meaning: "" } } : r,
        )
      : getMovement(source.slug as string, tonic ?? undefined);
    void request.then((r) => {
      if (cancelled) return;
      setState(r.ok ? { detail: r.data, error: null, loading: false } : { detail: null, error: failureText(r), loading: false });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, tonic]);
  return state;
}

/** Settings to start from (a saved progression opened from My Library). */
export type InitialSettings = Partial<Omit<ProgressionSettings, "slug">>;

export function MovementPlayer(source: Source & { initial?: InitialSettings }) {
  const initial = source.initial;
  const [tonic, setTonic] = useState<string | null>(initial?.tonic ?? null);
  const { detail, error, loading } = useMovement(source, tonic);
  const movement: Built | null = detail?.movement ?? null;

  const [level, setLevel] = useState<Level>(initial?.level ?? "intermediate");
  const [compare, setCompare] = useState<Level | null>(null);
  const [handMode, setHandMode] = useState<HandMode>(initial?.hands ?? "both");
  const [tempo, setTempo] = useState(initial?.tempo ?? 80);
  const [loop, setLoop] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [activeStep, setActiveStep] = useState(0);
  const [picked, setPicked] = useState(0);
  const [audioProblem, setAudioProblem] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [held, setHeld] = useState<ReadonlySet<number>>(new Set());

  const stageRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const progressRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<PianoAudio | null>(null);
  const run = useRef<{ pb: Playback; startedAt: number; fromBeat: number; tempo: number; raf: number } | null>(null);

  const versions = useMemo(() => new Map<Level, Version>((movement?.versions ?? []).map((v) => [v.level, v])), [movement]);
  const available = LEVELS.filter((l) => versions.has(l));
  const version = versions.get(level) ?? versions.get(available[0] as Level);
  const hands = HANDS[handMode];

  // What the loop callbacks need, kept in a ref so they never read stale values.
  const live = useRef({ version, hands, tempo, loop, layers: prefs.layers });
  live.current = { version, hands, tempo, loop, layers: prefs.layers };

  const audio = useCallback(() => (audioRef.current ??= new PianoAudio()), []);

  useEffect(() => setPrefs(loadPrefs(window.localStorage)), []);
  useEffect(() => {
    audio().setVolume(prefs.volume);
    audio().setTuning(prefs.a4);
  }, [audio, prefs.volume, prefs.a4]);

  // First load (or a new movement): pick a level that exists and the movement's own tempo.
  const slugRef = useRef<string | null>(null);
  const firstLoad = useRef(true);
  useEffect(() => {
    if (!movement) return;
    if (slugRef.current !== movement.slug) {
      slugRef.current = movement.slug;
      // A saved progression keeps the tempo it was saved with; otherwise the movement's own.
      setTempo(firstLoad.current && initial?.tempo ? initial.tempo : movement.tempo);
      firstLoad.current = false;
      setCompare(null);
      setPicked(0);
    }
    const have = movement.versions.map((v) => v.level);
    setLevel((l) => (have.includes(l) ? l : (have[0] as Level)));
    setCompare((c) => (c && have.includes(c) ? c : null));
  }, [movement]);

  const stopSound = useCallback(() => {
    const r = run.current;
    if (r) {
      cancelAnimationFrame(r.raf);
      r.pb.stop();
      run.current = null;
    }
    audioRef.current?.allNotesOff();
  }, []);

  const stop = useCallback(() => {
    stopSound();
    setPlaying(false);
    if (progressRef.current) progressRef.current.style.width = "0%";
  }, [stopSound]);

  const startFrom = useCallback(
    async (fromBeat: number) => {
      const a = audio();
      if (!(await a.resume())) {
        setAudioProblem("This browser could not start sound. The chords are still shown on the keyboard.");
        return;
      }
      setAudioProblem(null);
      stopSound();
      const { version: v, hands: h, tempo: t, layers } = live.current;
      if (!v) return;
      const pb = a.schedule(eventsFrom(v, fromBeat, h), t, layers);
      const startedAt = performance.now();
      const tick = () => {
        const cur = run.current;
        const lv = live.current.version;
        if (!cur || !lv) return;
        const beat = cur.fromBeat + (performance.now() - cur.startedAt) / 1000 / beatSeconds(cur.tempo);
        if (beat >= lv.total_beats) {
          if (live.current.loop) void startFrom(0);
          else stop();
          return;
        }
        setActiveStep(stepAtBeat(lv, beat));
        if (progressRef.current) progressRef.current.style.width = `${(beat / lv.total_beats) * 100}%`;
        cur.raf = requestAnimationFrame(tick);
      };
      run.current = { pb, startedAt, fromBeat, tempo: t, raf: 0 };
      setActiveStep(stepAtBeat(v, fromBeat));
      setPlaying(true);
      run.current.raf = requestAnimationFrame(tick);
    },
    [audio, stop, stopSound],
  );

  const beatNow = (): number => {
    const r = run.current;
    return r ? r.fromBeat + (performance.now() - r.startedAt) / 1000 / beatSeconds(r.tempo) : 0;
  };

  // Changing the version, the hands or the tempo while playing carries on from the same place.
  const restartKey = `${version?.level}|${handMode}|${tempo}`;
  const lastRestart = useRef(restartKey);
  useEffect(() => {
    if (lastRestart.current === restartKey) return;
    lastRestart.current = restartKey;
    if (run.current && version) void startFrom(resumeBeat(beatNow(), version));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restartKey]);

  useEffect(() => () => stopSound(), [stopSound]);
  useEffect(() => stop, [tonic, stop]); // leaving a key stops the music in the old one

  const shown = playing ? activeStep : picked;
  const step: Step | undefined = version?.steps[Math.min(shown, (version?.steps.length ?? 1) - 1)];
  const overlay = useMemo(() => (step ? overlayFromStep(step, hands) : null), [step, hands]);

  useEffect(() => {
    const el = scrollRef.current;
    const mid = step ? centreMidi(step) : null;
    const k = mid === null ? undefined : keyFor(mid);
    if (el && k) el.scrollLeft = Math.max(0, (k.x + 0.5) * prefs.keyWidth - el.clientWidth / 2);
  }, [step, prefs.keyWidth]);

  const audition = async (index: number) => {
    const v = live.current.version;
    if (!v) return;
    stop();
    setPicked(index);
    if (!(await audio().resume())) return;
    const s = v.steps[index];
    if (s) audio().schedule(stepEvent(s, hands), 120, prefs.layers);
  };

  useStickyScrollPadding(stageRef, Boolean(movement && version));

  const keyChoices = movement?.transposition_options ?? [];
  const homeTonic = movement?.key.tonic ?? "";

  if (loading && !movement) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading movement">
        <Skeleton className="h-56" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (error || !movement || !version) {
    return <Notice tone="error">{error ?? "This movement could not be loaded."}</Notice>;
  }

  const columns: Level[] = compare && compare !== level ? [level, compare] : [level];

  return (
    <div className="space-y-6">
      <div ref={stageRef} className="sticky top-[3.6rem] z-10 lg:top-2 [@media(max-height:620px)]:static">
        <div className="rounded-xl border border-line bg-surface p-3 shadow-md">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="min-h-9 text-sm" aria-live="polite">
              {overlay ? (
                <span>
                  <span className="text-muted">{playing ? "Playing " : "Showing "}</span>
                  <span className="font-semibold">{prettyNote(overlay.title)}</span>
                  {step ? <span className="text-muted"> · {step.inversion}</span> : null}
                </span>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => (playing ? stop() : void startFrom(0))}
                className={buttonStyles({ variant: "primary" })}
              >
                {playing ? <Pause aria-hidden className="h-4 w-4" /> : <Play aria-hidden className="h-4 w-4" />}
                {playing ? "Stop" : "Play"}
              </button>
              <button
                type="button"
                aria-pressed={loop}
                onClick={() => setLoop((l) => !l)}
                className={`${buttonStyles({ variant: "secondary" })} ${loop ? "border-accent" : ""}`}
              >
                <Repeat aria-hidden className="h-4 w-4" /> Loop
              </button>
            </div>
          </div>
          <PianoKeyboard
            keyWidth={prefs.keyWidth}
            held={held}
            overlay={overlay}
            labels={{ mode: prefs.labels, accidentals: prefs.accidentals, middleC: prefs.middleC, unicode: prefs.unicode }}
            scrollRef={scrollRef}
            onKeyDown={(n, v) => {
              void audio().resume().then(() => audio().noteOn(n, v, prefs.layers));
              setHeld((h) => new Set(h).add(n));
            }}
            onKeyUp={(n) => {
              audio().noteOff(n);
              setHeld((h) => {
                const next = new Set(h);
                next.delete(n);
                return next;
              });
            }}
          />
          <div className="mt-2 h-1 overflow-hidden rounded bg-surface-2" aria-hidden>
            <div ref={progressRef} className="h-full w-0 bg-accent" />
          </div>
          <ul className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted" aria-label="What the marks on the keys mean">
            <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-key-white bg-dot ring-1 ring-line" /> Root</li>
            <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-dot bg-dot-soft" /> Chord tone</li>
            <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-dashed border-muted bg-key-white" /> Added note</li>
            <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-sm border-2 border-dot bg-dot-soft" /> Bass note (square)</li>
            <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-4 bg-hand-left" /> Left hand</li>
            <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-4 bg-hand-right" /> Right hand</li>
          </ul>
        </div>
      </div>

      {audioProblem ? <Notice tone="error">{audioProblem}</Notice> : null}
      {detail?.live && !source.previewId ? (
        <Notice>
          Built just now in {prettyNote(tonic ?? "")} from the same chord pattern. The reviewed version is in{" "}
          {prettyNote(homeTonic)}.
        </Notice>
      ) : null}
      {source.previewId ? <Notice>Preview of an unpublished movement. Learners cannot see this.</Notice> : null}

      <section className="grid gap-5 rounded-xl border border-line bg-surface p-5 lg:grid-cols-4" aria-label="Practice controls">
        <fieldset className="lg:col-span-2">
          <legend className="mb-1.5 text-sm font-medium">Level</legend>
          <div className="flex flex-wrap gap-1.5">
            {available.map((l) => (
              <button
                key={l}
                type="button"
                aria-pressed={level === l}
                onClick={() => {
                  setLevel(l);
                  if (compare === l) setCompare(null);
                }}
                className={`min-h-11 rounded-lg border px-3 text-sm font-semibold ${level === l ? "border-accent bg-accent text-accent-fg" : "border-line bg-surface hover:bg-surface-2"}`}
              >
                {LEVEL_INFO[l].label}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-muted">{version.voicing_type}</p>
          {available.length > 1 ? (
            <label className="mt-3 flex min-h-11 items-center gap-2 text-sm">
              <span className="font-medium">Compare with</span>
              <select
                value={compare ?? ""}
                onChange={(e) => setCompare((e.target.value || null) as Level | null)}
                className="min-h-11 rounded-lg border border-line bg-surface px-3 text-sm"
              >
                <option value="">Nothing</option>
                {available.filter((l) => l !== level).map((l) => (
                  <option key={l} value={l}>{LEVEL_INFO[l].label}</option>
                ))}
              </select>
            </label>
          ) : null}
        </fieldset>

        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Hands</legend>
          <div className="flex flex-col gap-1.5">
            {(Object.keys(HANDS) as HandMode[]).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={handMode === m}
                onClick={() => setHandMode(m)}
                className={`min-h-11 rounded-lg border px-3 text-left text-sm font-semibold ${handMode === m ? "border-accent bg-accent text-accent-fg" : "border-line bg-surface hover:bg-surface-2"}`}
              >
                {HAND_LABEL[m]}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="space-y-4">
          <label className="block text-sm">
            <span className="mb-1.5 flex justify-between font-medium">
              <span>Tempo</span>
              <span className="text-muted">{tempo} BPM</span>
            </span>
            <input
              type="range" min={30} max={200} value={tempo}
              onChange={(e) => setTempo(Number(e.target.value))}
              className="w-full accent-[rgb(var(--c-accent))]"
            />
          </label>
          {!source.previewId ? (
            <label className="block text-sm">
              <span className="mb-1.5 block font-medium">Key</span>
              <select
                value={tonic ?? homeTonic}
                onChange={(e) => setTonic(e.target.value === homeTonic ? null : e.target.value)}
                className="min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm"
              >
                {keyChoices.map((k) => (
                  <option key={k} value={k}>
                    {prettyNote(k)} {movement.key.mode}{k === homeTonic ? " (original)" : ""}
                  </option>
                ))}
              </select>
              {loading ? <span className="mt-1 block text-xs text-muted" role="status">Working out the voicings…</span> : null}
            </label>
          ) : null}
        </div>
      </section>

      <div className={`grid gap-5 ${columns.length > 1 ? "lg:grid-cols-2" : ""}`}>
        {columns.map((lv) => {
          const v = versions.get(lv);
          if (!v) return null;
          return (
            <section key={lv} aria-label={`${LEVEL_INFO[lv].label} version`} className="rounded-xl border border-line bg-surface p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-base font-semibold">{LEVEL_INFO[lv].label}</h2>
                {columns.length > 1 ? (
                  <button
                    type="button"
                    aria-pressed={level === lv}
                    onClick={() => setLevel(lv)}
                    className={buttonStyles({ variant: level === lv ? "primary" : "secondary" })}
                  >
                    {level === lv ? "Hearing this" : "Hear this version"}
                  </button>
                ) : null}
              </div>
              <p className="mb-3 text-xs text-muted">{v.voicing_type}</p>
              <ol className="space-y-2">
                {v.steps.map((s) => {
                  const current = s.index === Math.min(shown, v.steps.length - 1);
                  return (
                    <li key={s.index}>
                      <button
                        type="button"
                        onClick={() => void audition(s.index)}
                        aria-current={current ? "step" : undefined}
                        className={`w-full rounded-lg border p-3 text-left transition-colors ${current ? "border-accent bg-accent-soft" : "border-line hover:bg-surface-2"}`}
                      >
                        <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                          <span className="text-lg font-bold">{prettyNote(s.symbol)}</span>
                          <span className="text-sm text-muted">
                            {s.roman ?? ""} · {s.duration} beat{s.duration === 1 ? "" : "s"}
                          </span>
                        </span>
                        <span className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-sm">
                          <span className="font-medium text-hand-left">Left</span>
                          <span>{s.left_names.length ? s.left_names.map(prettyNote).join("  ") : "rests"}</span>
                          <span className="font-medium text-hand-right">Right</span>
                          <span>{s.right_names.length ? s.right_names.map(prettyNote).join("  ") : "rests"}</span>
                        </span>
                        <span className="mt-1 block text-xs text-muted">
                          {s.inversion}
                          {s.role === "substitution" ? " · substitute chord" : ""}
                          {s.omitted.length ? ` · leaves out ${s.omitted.join(", ")}` : ""}
                        </span>
                      </button>
                      {s.explanation.length ? (
                        <details className="mt-1 px-1 text-xs text-muted">
                          <summary className="cursor-pointer py-1">Why this voicing</summary>
                          <ul className="list-disc space-y-0.5 pl-5">
                            {s.explanation.map((line) => <li key={line}>{line}</li>)}
                          </ul>
                        </details>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            </section>
          );
        })}
      </div>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-xl border border-line bg-surface p-5">
          <h2 className="mb-2 text-base font-semibold">Why it works</h2>
          <p className="max-w-[64ch] text-sm leading-relaxed">{version.theory_explanation || "No explanation yet."}</p>
          {movement.author ? <p className="mt-3 text-xs text-muted">By {movement.author}{movement.source ? ` · ${movement.source}` : ""}</p> : null}
        </div>
        <div className="rounded-xl border border-line bg-surface p-5">
          <h2 className="mb-2 text-base font-semibold">How to practise</h2>
          <p className="max-w-[64ch] text-sm leading-relaxed">{version.practice}</p>
          {version.variations.length ? (
            <>
              <h3 className="mb-1 mt-4 text-sm font-semibold">Variations</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm">{version.variations.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          ) : null}
        </div>
      </section>

      {version.warnings.length ? <Notice>{version.warnings.join(" ")}</Notice> : null}
      <p className="text-xs text-muted">
        Voicings are rule-based suggestions that are valid and playable, not the only way a pianist might play this.{" "}
        {detail?.score_meaning}
      </p>
      {!source.previewId && source.slug ? (
        <section className="rounded-xl border border-line bg-surface p-5">
          <h2 className="mb-1 text-base font-semibold">My Library</h2>
          <p className="mb-3 text-sm text-muted">Save this progression with the key, level, hands and tempo you chose.</p>
          <SaveToLibrary
            kind="progression"
            defaultTitle={`${movement.name} in ${tonic ?? homeTonic}`.slice(0, 120)}
            build={() => ({ data: serializeProgression({ slug: source.slug as string, tonic, level, hands: handMode, tempo }) })}
          />
        </section>
      ) : null}
      {!source.previewId ? (
        <Link href="/progressions" className={buttonStyles({ variant: "ghost" })}>← All movements</Link>
      ) : null}
    </div>
  );
}
