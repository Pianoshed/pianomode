"use client";

import { FileAudio, Pause, Play, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PianoKeyboard } from "@/components/piano/PianoKeyboard";
import { prettyNote, selectClass } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type Correction, type InterpretResponse, interpretAudio } from "@/lib/audio/api";
import { type ChordSet, type DecodeOptions, DEFAULT_DECODE, decodeChords } from "@/lib/audio/chords";
import { type ChromaTrack, SAMPLE_RATE, extractAsync } from "@/lib/audio/chroma";
import { AudioLoadError, type LoadedAudio, loadAudio } from "@/lib/audio/decode";
import { QUALITY_INTERVALS, synthProgression, voicing } from "@/lib/audio/synth";
import {
  AMBIGUITY_LEVELS,
  type AmbiguityLevel,
  EditError,
  addEdit,
  buildInterpretRequest,
  correctionSummary,
  deleteEdit,
  edgeEdits,
  gapAround,
  hypothesisAt,
  look,
  mergeEdits,
  relabelEdit,
  splitEdits,
} from "@/lib/audio/studio";
import { encodeWav } from "@/lib/audio/wav";
import type { Prefer } from "@/lib/midi/api";
import { formatTime, rateLimitAdvice } from "@/lib/midi/studio";
import { PianoAudio } from "@/lib/piano/audio";
import { keyFor } from "@/lib/piano/keys";
import { overlayFromChord } from "@/lib/piano/highlight";
import { DEFAULT_PREFS, type Prefs, loadPrefs } from "@/lib/piano/prefs";
import { type ChordConstruct, constructChord } from "@/lib/piano/theoryApi";
import { useStickyScrollPadding } from "@/lib/useStickyScrollPadding";
import { SaveToLibrary } from "@/components/library/SaveToLibrary";
import { getItem } from "@/lib/library/api";
import { type AudioProjectSettings, restoreAudioProject, sameRecording, serializeAudioProject } from "@/lib/library/audioProject";
import { AudioTimeline } from "./AudioTimeline";
import { HypothesisDetails } from "./HypothesisDetails";
import { Waveform } from "./Waveform";

type Source = { name: string; url: string; samples: Float32Array; duration: number; info: string };
type Stage = "idle" | "decoding" | "analysing" | "ready";
const TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const card = "rounded-xl border border-line bg-surface p-5";

/** C, Am, F, G7: synthesised in the browser, then analysed like any file. Its right answer is known. */
function exampleAudio(): LoadedAudio {
  const spec: [number, string][] = [[0, "maj"], [9, "min"], [5, "maj"], [7, "7"]];
  const samples = synthProgression(
    spec.map(([root, q]) => {
      const v = voicing(root, QUALITY_INTERVALS[q] as number[]);
      return { notes: v.notes, bass: v.bass, seconds: 2.5 };
    }),
  );
  return { samples, duration: samples.length / SAMPLE_RATE, sampleRate: SAMPLE_RATE, originalRate: SAMPLE_RATE, channels: 1 };
}

export function AudioAnalyzer({ projectId }: { projectId?: string } = {}) {
  const [source, setSource] = useState<Source | null>(null);
  const [project, setProject] = useState<{ id: string; title: string } | null>(null);
  const [waitingFor, setWaitingFor] = useState<AudioProjectSettings | null>(null);
  const [projectLoading, setProjectLoading] = useState(Boolean(projectId));
  const [loadCount, setLoadCount] = useState(0); // changes whenever a recording is opened, so Save starts fresh
  const pendingSaved = useRef<AudioProjectSettings | null>(null);
  const projectRequested = useRef(false);
  const projectUsed = useRef(false); // the saved project has been applied to a recording
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [track, setTrack] = useState<ChromaTrack | null>(null);
  const [applied, setApplied] = useState<DecodeOptions>(DEFAULT_DECODE);
  const [draft, setDraft] = useState<DecodeOptions>(DEFAULT_DECODE);
  const [pending, setPending] = useState<DecodeOptions | null>(null);
  const [keyChoice, setKeyChoice] = useState<{ tonic: string; mode: string } | null>(null);
  const [prefer, setPrefer] = useState<Prefer>("sharps");
  const [ambiguity, setAmbiguity] = useState<AmbiguityLevel>("normal");
  const [corrections, setCorrections] = useState<Correction[]>([]);
  const [result, setResult] = useState<InterpretResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [chord, setChord] = useState<{ symbol: string; res: ChordConstruct } | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [dragging, setDragging] = useState(false);
  const [boxWidth, setBoxWidth] = useState(800);

  const stageRef = useRef<HTMLDivElement | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const audioEl = useRef<HTMLAudioElement | null>(null);
  const pianoAudio = useRef<PianoAudio | null>(null);
  const abort = useRef<AbortController | null>(null);
  const urlRef = useRef<string | null>(null);
  const chordCache = useRef(new Map<string, ChordConstruct>());
  const piano = useCallback(() => (pianoAudio.current ??= new PianoAudio()), []);

  useEffect(() => setPrefs(loadPrefs(window.localStorage)), []);
  useStickyScrollPadding(stageRef, stage === "ready");
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBoxWidth(el.clientWidth));
    ro.observe(el);
    setBoxWidth(el.clientWidth);
    return () => ro.disconnect();
  }, [stage]);
  useEffect(
    () => () => {
      abort.current?.abort();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      pianoAudio.current?.allNotesOff();
    },
    [],
  );

  // A saved analysis opened from My Library: put its settings back now, and its corrections once
  // the same recording is opened again (the recording itself is never stored).
  useEffect(() => {
    if (!projectId || projectRequested.current) return; // strict mode runs effects twice in development
    projectRequested.current = true;
    void (async () => {
      const r = await getItem(projectId);
      if (!r.ok) {
        setLoadError(r.message);
      } else {
        const saved = restoreAudioProject(r.data.data);
        setProject({ id: r.data.id, title: r.data.title });
        setApplied(saved.decode);
        setDraft(saved.decode);
        setKeyChoice(saved.keyChoice);
        setPrefer(saved.prefer);
        setAmbiguity(saved.ambiguity);
        pendingSaved.current = saved;
        setWaitingFor(saved);
      }
      setProjectLoading(false);
    })();
  }, [projectId]);

  // ------------------------------------------------------------------ loading and analysing
  const begin = useCallback(async (blob: Blob, name: string, pre?: LoadedAudio) => {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    audioEl.current?.pause();
    setPlaying(false);
    setLoadError(null);
    setProblem(null);
    setResult(null);
    setSel(null);
    setCorrections([]);
    setPending(null);
    setTime(0);
    setStage("decoding");
    setProgress(0);
    setLoadCount((c) => c + 1);
    if (projectUsed.current) {
      // A second recording after the saved one is new work, not a continuation of the project.
      projectUsed.current = false;
      setProject(null);
    }
    try {
      const loaded = pre ?? (await loadAudio(blob));
      if (ac.signal.aborted) return;
      setStage("analysing");
      const t = await extractAsync(loaded.samples, { signal: ac.signal, onProgress: setProgress });
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      setSource({
        name,
        url,
        samples: loaded.samples,
        duration: loaded.duration,
        info: `${formatTime(loaded.duration)} · ${loaded.channels === 1 ? "mono" : `${loaded.channels} channels, mixed to mono`} · ${(loaded.originalRate / 1000).toFixed(1)} kHz, analysed at ${(SAMPLE_RATE / 1000).toFixed(1)} kHz`,
      });
      setTrack(t);
      const saved = pendingSaved.current;
      if (saved) {
        // The first recording opened after a saved analysis gets its corrections back, but only
        // if it is about the same length: corrections are tied to exact times in the recording.
        pendingSaved.current = null;
        projectUsed.current = true;
        setWaitingFor(null);
        if (sameRecording(saved, loaded.duration)) setCorrections(saved.corrections);
        else setProblem("This recording is a different length from the saved one, so your saved corrections were not applied. Your other settings were.");
      }
      setStage("ready");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setStage("idle");
      setSource(null);
      setTrack(null);
      setLoadError(e instanceof AudioLoadError ? e.message : "Something went wrong while analysing this file.");
    }
  }, []);

  const regions = useMemo(() => (track ? decodeChords(track, applied) : []), [track, applied]);
  const depKey = useMemo(() => JSON.stringify([regions, keyChoice, prefer, ambiguity, corrections]), [regions, keyChoice, prefer, ambiguity, corrections]);

  // ------------------------------------------------------------------ interpreting
  const seq = useRef(0);
  const [retry, setRetry] = useState(0);
  const retries = useRef(0);
  const retryTimer = useRef(0);
  const lastKey = useRef("");
  const resultKey = useRef("");
  useEffect(() => {
    if (!regions.length || stage !== "ready") return;
    if (resultKey.current === depKey) return; // a correction was just checked with this exact request
    if (lastKey.current !== depKey) {
      lastKey.current = depKey;
      retries.current = 0;
    }
    window.clearTimeout(retryTimer.current);
    const mine = ++seq.current;
    setBusy(true);
    const timer = window.setTimeout(() => {
      void interpretAudio(buildInterpretRequest(regions, { key: keyChoice, prefer, scoreMargin: AMBIGUITY_LEVELS[ambiguity], corrections })).then((r) => {
        if (mine !== seq.current) return;
        setBusy(false);
        if (r.ok) {
          retries.current = 0;
          resultKey.current = depKey;
          setResult(r.data);
          setProblem(null);
        } else if (r.code === "rate_limited") {
          const advice = rateLimitAdvice(retries.current);
          setProblem(advice.message);
          if (advice.retry) {
            retries.current++;
            setBusy(true);
            retryTimer.current = window.setTimeout(() => setRetry((n) => n + 1), advice.delayMs);
          }
        } else setProblem(failureText(r));
      });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(retryTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depKey, stage, retry]);

  const hyps = result?.hypotheses ?? [];
  const duration = source?.duration ?? 0;

  /** Check a correction with the server first; only keep it if the server accepts it. */
  const commit = async (edits: Correction[]) => {
    const next = [...corrections, ...edits];
    setBusy(true);
    const r = await interpretAudio(buildInterpretRequest(regions, { key: keyChoice, prefer, scoreMargin: AMBIGUITY_LEVELS[ambiguity], corrections: next }));
    setBusy(false);
    if (r.ok) {
      resultKey.current = JSON.stringify([regions, keyChoice, prefer, ambiguity, next]);
      setCorrections(next);
      setResult(r.data);
      setProblem(null);
    } else setProblem(failureText(r));
  };
  const attempt = (make: () => Correction[]) => {
    try {
      void commit(make());
    } catch (e) {
      setProblem(e instanceof EditError ? e.message : "That change could not be made.");
    }
  };

  // ------------------------------------------------------------------ settings that re-decode
  const changeDecode = (patch: Partial<DecodeOptions>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    if (corrections.length) setPending(next);
    else setApplied(next);
  };
  const confirmDecode = () => {
    if (!pending) return;
    setApplied(pending);
    setCorrections([]);
    setResult(null);
    setSel(null);
    setPending(null);
  };
  const cancelDecode = () => {
    setDraft(applied);
    setPending(null);
  };

  // ------------------------------------------------------------------ playback
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = -1;
    const tick = () => {
      const a = audioEl.current;
      if (a && Math.abs(a.currentTime - last) > 0.03) {
        last = a.currentTime;
        setTime(a.currentTime);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const togglePlay = async () => {
    const a = audioEl.current;
    if (!a) return;
    if (playing) {
      a.pause();
      return;
    }
    try {
      if (a.ended || a.currentTime >= duration - 0.05) a.currentTime = 0;
      await a.play();
    } catch {
      setProblem("This browser would not start the recording. Try the Play button again.");
    }
  };
  const seek = (t: number) => {
    const a = audioEl.current;
    if (a) a.currentTime = t;
    setTime(t);
    if (!playing) {
      const i = hypothesisAt(hyps, t);
      setSel(i >= 0 ? i : null);
    }
  };
  const playFrom = (t: number) => {
    seek(t);
    void audioEl.current?.play().catch(() => setProblem("This browser would not start the recording."));
  };

  // ------------------------------------------------------------------ what the keyboard shows
  const shownIdx = playing ? hypothesisAt(hyps, time) : sel;
  const shown = shownIdx !== null && shownIdx >= 0 ? (hyps[shownIdx] ?? null) : null;
  const symbol = shown?.symbol ?? null;
  useEffect(() => {
    if (!symbol) {
      setChord(null);
      return;
    }
    const cached = chordCache.current.get(symbol);
    if (cached) {
      setChord({ symbol, res: cached });
      return;
    }
    let cancelled = false;
    void constructChord({ symbol, octave: 4 }).then((r) => {
      if (cancelled) return;
      if (r.ok) {
        chordCache.current.set(symbol, r.data);
        setChord({ symbol, res: r.data });
      } else setChord(null);
    });
    return () => {
      cancelled = true;
    };
  }, [symbol]);
  const overlay = useMemo(() => {
    if (!chord || !shown || chord.symbol !== shown.symbol) return null;
    const o = overlayFromChord(chord.res, false);
    return { ...o, title: `${shown.origin === "user" ? "Your label" : "Heard (estimate)"}: ${chord.symbol}` };
  }, [chord, shown]);

  // Start around middle C rather than at the bass end, until a chord is chosen.
  useEffect(() => {
    const el = scrollRef.current;
    const k = keyFor(60);
    if (el && k && stage === "ready") el.scrollLeft = Math.max(0, (k.x + 0.5) * prefs.keyWidth - el.clientWidth / 2);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !overlay) return;
    const xs = [...overlay.marks.keys()].map((m) => keyFor(m)?.x ?? 0);
    const lo = Math.min(...xs) * prefs.keyWidth;
    const hi = (Math.max(...xs) + 1) * prefs.keyWidth;
    if (lo < el.scrollLeft || hi > el.scrollLeft + el.clientWidth) el.scrollLeft = Math.max(0, (lo + hi) / 2 - el.clientWidth / 2);
  }, [overlay, prefs.keyWidth]);

  const hear = async () => {
    if (!chord) return;
    audioEl.current?.pause();
    if (!(await piano().resume())) return;
    piano().schedule([{ notes: chord.res.midi_notes, start: 0, duration: 2 }], 60, prefs.layers);
  };

  const width = Math.max(boxWidth - 4, Math.min(12000, Math.round(duration * 24)));
  const playheadX = duration ? (time / duration) * width : 0;
  useEffect(() => {
    const el = boxRef.current;
    if (!el || !playing) return;
    if (playheadX < el.scrollLeft + 40 || playheadX > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, playheadX - 80);
  }, [playheadX, playing]);

  const gap = gapAround(hyps, time, duration);
  const key = result?.key ?? null;

  // ------------------------------------------------------------------ view
  return (
    <div className="space-y-6">
      <section
        aria-label="Open an audio file"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f) void begin(f, f.name);
        }}
        className={`${card} ${dragging ? "border-accent bg-accent-soft" : ""}`}
      >
        <div className="flex flex-wrap items-center gap-3">
          <label className={`${buttonStyles()} cursor-pointer`}>
            <Upload aria-hidden className="h-4 w-4" /> Choose an audio file
            <input
              type="file"
              accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac"
              className="sr-only"
              data-testid="audio-file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void begin(f, f.name);
                e.target.value = "";
              }}
            />
          </label>
          <button
            type="button"
            className={buttonStyles({ variant: "secondary" })}
            onClick={() => {
              const loaded = exampleAudio();
              void begin(new Blob([encodeWav(loaded.samples, SAMPLE_RATE)], { type: "audio/wav" }), "C - Am - F - G7 (example).wav", loaded);
            }}
          >
            <FileAudio aria-hidden className="h-4 w-4" /> Try an example
          </button>
          <span className="text-sm text-muted">or drop a WAV, MP3, M4A or OGG file here</span>
        </div>
        <p className="mt-3 text-xs text-muted">The recording is analysed on your device. Only the chord estimates are sent to be interpreted. The recording itself is never uploaded or kept; saving to My Library keeps only your settings and corrections.</p>
        <p className="mt-2 text-sm">
          <strong>How far to trust it.</strong> Chords are estimated from the sound with a simple method (it measures how much of each of the twelve notes is playing). It does best on a clear recording of one instrument or a small group. Singing, drums, effects and dense mixes make it less reliable, and it cannot tell instruments apart. Treat every chord as a suggestion to check against your ears.
        </p>
        {loadError ? <div className="mt-3"><Notice tone="error">{loadError}</Notice></div> : null}
        {projectLoading ? <div className="mt-3"><Notice>Opening your saved analysis…</Notice></div> : null}
        {waitingFor && project ? (
          <div className="mt-3">
            <Notice tone="info">
              <strong>{project.title}</strong> is open. Choose the same recording{waitingFor.fileName ? ` (${waitingFor.fileName})` : ""} to put your
              saved corrections back on it. The recording is not stored, so it has to come from your device.
            </Notice>
          </div>
        ) : null}
      </section>

      {stage === "decoding" || stage === "analysing" ? (
        <section className={card} aria-live="polite">
          <p className="text-sm font-medium">{stage === "decoding" ? "Reading the file…" : "Listening for chords…"}</p>
          <div className="mt-2 h-2 overflow-hidden rounded bg-surface-2" role="progressbar" aria-label="Analysis progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
            <div className="h-full bg-accent transition-[width]" style={{ width: `${stage === "decoding" ? 5 : Math.round(progress * 100)}%` }} />
          </div>
          <button type="button" onClick={() => abort.current?.abort()} className={`${buttonStyles({ variant: "secondary" })} mt-3`}>Cancel</button>
        </section>
      ) : null}

      {stage === "ready" && source ? (
        <>
          <section aria-label="File" className={card}>
            <h2 className="text-base font-semibold">{source.name}</h2>
            <p className="mt-1 text-sm text-muted">{source.info} · {regions.length} region{regions.length === 1 ? "" : "s"}</p>
          </section>

          <section aria-label="My Library" className={card}>
            <h2 className="mb-1 text-base font-semibold">My Library</h2>
            <p className="mb-3 text-sm text-muted">Keep your settings and corrections for this recording. The recording itself is not saved.</p>
            <SaveToLibrary
              key={`${project?.id ?? "new"}-${loadCount}`}
              kind="audio"
              defaultTitle={source.name.replace(/\.[A-Za-z0-9]{2,4}$/, "")}
              existing={project}
              disabled={busy}
              build={() => ({
                data: serializeAudioProject({
                  decode: applied,
                  keyChoice,
                  prefer,
                  ambiguity,
                  corrections,
                  fileName: source.name,
                  duration: source.duration,
                  summary: { chords: hyps.length, key: result?.key?.name ?? null },
                }),
              })}
            />
          </section>

          <div ref={stageRef} className="sticky top-[3.6rem] z-10 lg:top-2 [@media(max-height:620px)]:static">
            <div className="rounded-xl border border-line bg-surface p-3 shadow-md">
              <div className="mb-2.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="min-h-9 text-sm" aria-live="polite">
                  {overlay ? <span className="font-semibold">{prettyNote(overlay.title)}</span> : <span className="text-muted">{playing ? "Playing" : "Choose a chord to see it on the keys."}</span>}
                  <span className="ml-3 text-muted">{formatTime(time, true)} / {formatTime(duration)}</span>
                </div>
                <button type="button" onClick={() => void togglePlay()} className={buttonStyles({ variant: "primary" })}>
                  {playing ? <Pause aria-hidden className="h-4 w-4" /> : <Play aria-hidden className="h-4 w-4" />}
                  {playing ? "Pause" : "Play recording"}
                </button>
              </div>
              <PianoKeyboard
                keyWidth={prefs.keyWidth}
                held={new Set()}
                overlay={overlay}
                labels={{ mode: prefs.labels, accidentals: prefs.accidentals, middleC: prefs.middleC, unicode: prefs.unicode }}
                scrollRef={scrollRef}
                onKeyDown={(n, v) => void piano().resume().then(() => piano().noteOn(n, v, prefs.layers))}
                onKeyUp={(n) => piano().noteOff(n)}
              />
              <p className="mt-2 text-xs text-muted">The keys show the chord that was estimated, played in a standard position. They are not the notes in the recording.</p>
            </div>
          </div>
          {/* the recording itself, played by the browser; the controls above and below drive it */}
          <audio
            ref={audioEl}
            src={source.url}
            preload="auto"
            data-testid="recording"
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => {
              setPlaying(false);
              setTime(0);
            }}
          />

          {problem ? <Notice tone={busy ? "info" : "error"}>{problem}</Notice> : null}

          <section aria-label="Chords in the recording" className={card}>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">Chords</h2>
              <span className="flex items-center gap-2 text-sm text-muted" aria-live="polite">
                {busy ? "Updating…" : correctionSummary(corrections.length)}
                {corrections.length ? (
                  <>
                    <button type="button" onClick={() => setCorrections((c) => c.slice(0, -1))} className={buttonStyles({ variant: "secondary" })}>Undo</button>
                    <button type="button" onClick={() => setCorrections([])} className={buttonStyles({ variant: "ghost" })}>Reset all</button>
                  </>
                ) : null}
              </span>
            </div>
            <div ref={boxRef} className="relative overflow-x-auto pb-2" data-testid="timeline-scroll">
              <div className="relative" style={{ width }}>
                <Waveform samples={source.samples} duration={duration} regions={hyps} width={width} onSeek={seek} />
                <div className="mt-1.5">
                  {result ? <AudioTimeline hypotheses={hyps} selected={sel} current={playing ? shownIdx : null} width={width} duration={duration} onSelect={(i) => { setSel(i); const h = hyps[i]; if (h && !playing) setTime(h.start); }} /> : <p className="py-4 text-sm text-muted">Interpreting…</p>}
                </div>
                <div aria-hidden className="pointer-events-none absolute top-0 h-full w-0.5 bg-accent" style={{ left: playheadX }} data-testid="playhead" />
              </div>
            </div>
            <label className="mt-2 flex items-center gap-3 text-sm">
              <span className="font-medium">Position</span>
              <input type="range" min={0} max={Math.max(0.1, duration)} step={0.05} value={Math.min(time, duration)} onChange={(e) => seek(Number(e.target.value))} aria-label="Playback position" aria-valuetext={formatTime(time, true)} className="w-full accent-[rgb(var(--c-accent))]" />
            </label>
            <p className="mt-2 text-xs text-muted">Solid outline: a clear estimate. Dashed with a question mark: another reading is almost as likely. Dotted: no chord. Orange outline: set by you.</p>
          </section>

          {pending ? (
            <Notice tone="error">
              <p>Changing this setting listens again and replaces your {corrections.length} correction{corrections.length === 1 ? "" : "s"}.</p>
              <div className="mt-2 flex gap-2">
                <button type="button" onClick={confirmDecode} className={buttonStyles()}>Replace them</button>
                <button type="button" onClick={cancelDecode} className={buttonStyles({ variant: "secondary" })}>Keep my corrections</button>
              </div>
            </Notice>
          ) : null}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="min-w-0">
              {shown && shownIdx !== null && shownIdx >= 0 ? (
                <HypothesisDetails
                  h={shown}
                  original={result?.original?.[shownIdx] ?? null}
                  index={shownIdx}
                  count={hyps.length}
                  playhead={time}
                  canAddHere={gap !== null}
                  busy={busy}
                  onHear={() => void hear()}
                  onPlayFrom={() => playFrom(shown.start)}
                  onRelabel={(label) => attempt(() => [relabelEdit(shownIdx, label)])}
                  onEdge={(edge, to) => attempt(() => edgeEdits(hyps, shownIdx, edge, to, duration))}
                  onSplit={() => attempt(() => splitEdits(hyps, shownIdx, time))}
                  onMerge={() => attempt(() => mergeEdits(hyps, shownIdx))}
                  onDelete={() => attempt(() => [deleteEdit(shownIdx)])}
                  onAdd={(label) => attempt(() => [addEdit(gap, label)])}
                />
              ) : (
                <section className={card}>
                  <p className="text-sm text-muted">
                    {hyps.length ? "Choose a chord on the timeline to see what was heard, check the alternatives and correct it." : "Interpreting…"}
                  </p>
                  {gap ? (
                    <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); attempt(() => [addEdit(gap, String(f.get("label") ?? ""))]); e.currentTarget.reset(); }}>
                      <label className="block text-sm"><span className="mb-1.5 block font-medium">Add a chord at the playhead</span>
                        <input name="label" className="min-h-11 w-48 rounded-lg border border-line bg-surface px-3 text-sm" maxLength={40} placeholder="chord, for example G7" /></label>
                      <button type="submit" className={buttonStyles({ variant: "secondary" })}>Add</button>
                    </form>
                  ) : null}
                </section>
              )}
            </div>

            <div className="min-w-0 space-y-6">
              <section aria-label="Settings" className={`${card} space-y-4`}>
                <h2 className="text-base font-semibold">How to listen</h2>
                <label className="block text-sm"><span className="mb-1.5 block font-medium">Chord types</span>
                  <select className={selectClass} value={draft.set} onChange={(e) => changeDecode({ set: e.target.value as ChordSet })}>
                    <option value="sevenths">Major, minor and sevenths</option>
                    <option value="triads">Major and minor only</option>
                  </select>
                  <span className="mt-1 block text-xs text-muted">Choose major and minor only for simple songs: it avoids mistaking a plain chord for a seventh.</span></label>
                <label className="block text-sm"><span className="mb-1.5 flex justify-between font-medium"><span>Chord changes</span><span className="text-muted">{draft.stability < 0.34 ? "more" : draft.stability > 0.66 ? "fewer" : "balanced"}</span></span>
                  <input type="range" min={0} max={1} step={0.05} value={1 - draft.stability} onChange={(e) => changeDecode({ stability: 1 - Number(e.target.value) })} aria-label="How readily to mark a change of chord" className="w-full accent-[rgb(var(--c-accent))]" /></label>
                <label className="block text-sm"><span className="mb-1.5 block font-medium">Shortest chord</span>
                  <select className={selectClass} value={draft.minDuration} onChange={(e) => changeDecode({ minDuration: Number(e.target.value) })}>
                    {[0.2, 0.4, 0.8, 1.5].map((s) => <option key={s} value={s}>{s} seconds</option>)}
                  </select></label>
              </section>

              <section aria-label="Key" className={`${card} space-y-3`}>
                <h2 className="text-base font-semibold">Key</h2>
                {key ? (
                  <p className="text-sm"><span className="font-semibold">{prettyNote(key.name)}</span> <span className="text-muted">({key.signature})</span>
                    <span className="ml-1 rounded bg-surface-2 px-1.5 py-0.5 text-xs text-muted">{result?.key_source === "estimated" ? "estimated" : "chosen by you"}</span></p>
                ) : <p className="text-sm text-muted">No key could be estimated, so there are no Roman numerals.</p>}
                {result?.key_estimate?.ambiguous ? <p className="text-sm">Another key is nearly as likely, so treat this as a guess.</p> : null}
                {result?.warnings.map((w) => <p key={w} className="text-xs text-muted">{w}</p>)}
                <div className="grid grid-cols-2 gap-3">
                  <label className="col-span-2 block text-sm"><span className="mb-1.5 block font-medium">Key to use</span>
                    <span className="flex gap-2">
                      <select aria-label="Tonic" className={selectClass} value={keyChoice?.tonic ?? ""} onChange={(e) => setKeyChoice(e.target.value ? { tonic: e.target.value, mode: keyChoice?.mode ?? "major" } : null)}>
                        <option value="">Estimate it</option>
                        {TONICS.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                      <select aria-label="Mode" className={selectClass} disabled={!keyChoice} value={keyChoice?.mode ?? "major"} onChange={(e) => keyChoice && setKeyChoice({ ...keyChoice, mode: e.target.value })}>
                        <option value="major">major</option>
                        <option value="minor">minor</option>
                      </select>
                    </span></label>
                  <label className="col-span-2 block text-sm"><span className="mb-1.5 block font-medium">Uncertainty warnings</span>
                    <select className={selectClass} value={ambiguity} onChange={(e) => setAmbiguity(e.target.value as AmbiguityLevel)}>
                      <option value="fewer">Fewer (only very close calls)</option>
                      <option value="normal">Normal</option>
                      <option value="more">More (cautious)</option>
                    </select>
                    <span className="mt-1 block text-xs text-muted">How close another chord must score before this one is marked with a question mark. Not calibrated on real recordings.</span></label>
                  <label className="col-span-2 block text-sm"><span className="mb-1.5 block font-medium">Spelling</span>
                    <select className={selectClass} value={prefer} onChange={(e) => setPrefer(e.target.value as Prefer)}>
                      <option value="sharps">Sharps</option>
                      <option value="flats">Flats</option>
                    </select></label>
                </div>
              </section>
              {result ? <p className="text-xs text-muted">{result.evidence_note}</p> : null}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
