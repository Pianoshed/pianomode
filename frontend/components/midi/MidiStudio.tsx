"use client";

import { FileMusic, Pause, Play, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PianoKeyboard } from "@/components/piano/PianoKeyboard";
import { prettyNote, selectClass } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type AnalyzeResponse, type Grid, type Hand, type Prefer, analyzeMidi } from "@/lib/midi/api";
import { SaveToLibrary } from "@/components/library/SaveToLibrary";
import { getItem, getItemFile } from "@/lib/library/api";
import { restoreMidiProject, serializeMidiProject } from "@/lib/library/midiProject";
import { MidiError, type ParsedMidi, parseMidi } from "@/lib/midi/smf";
import {
  AUDIO_LATENCY_SEC,
  type HandEdits,
  type HandFilter,
  type HandNote,
  PUMP_MS,
  StudioError,
  type TrackEdit,
  type TrackState,
  type Window,
  applyTrackEdits,
  buildAnalyzeRequest,
  flipHand,
  formatTime,
  freeTrack,
  makeRollView,
  midiNoteName,
  neighbour,
  notesSounding,
  overlayForMoment,
  pumpEvents,
  rateLimitAdvice,
  rollWidth,
  rollX,
  segmentAt,
  summarizeTracks,
  totalSeconds,
  windowFrom,
  withHands,
} from "@/lib/midi/studio";
import { PianoAudio, type Playback } from "@/lib/piano/audio";
import { keyFor } from "@/lib/piano/keys";
import { DEFAULT_PREFS, type Prefs, loadPrefs } from "@/lib/piano/prefs";
import { useStickyScrollPadding } from "@/lib/useStickyScrollPadding";
import { ChordTimeline } from "./ChordTimeline";
import { PianoRoll } from "./PianoRoll";
import { SegmentDetails } from "./SegmentDetails";
import { ExportPanel } from "./ExportPanel";
import { TrackPanel } from "./TrackPanel";

type Analysis = { response: AnalyzeResponse; windowStartTick: number; ppq: number };
const TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const HAND_FILTERS: { value: HandFilter; label: string }[] = [
  { value: "both", label: "Both hands" },
  { value: "L", label: "Left hand only" },
  { value: "R", label: "Right hand only" },
];
const card = "rounded-xl border border-line bg-surface p-5";

function defaultStates(p: ParsedMidi): Record<number, TrackState> {
  return Object.fromEntries(p.tracks.filter((t) => t.noteCount > 0).map((t) => [t.index, { hand: null, muted: t.drumsOnly, solo: false } as TrackState]));
}

export function MidiStudio({ projectId }: { projectId?: string } = {}) {
  const [fileName, setFileName] = useState<string | null>(null);
  const [project, setProject] = useState<{ id: string; title: string } | null>(null);
  const [projectLoading, setProjectLoading] = useState(Boolean(projectId));
  const [loadCount, setLoadCount] = useState(0); // changes whenever a file is shown, so Save starts fresh
  const bytesRef = useRef<ArrayBuffer | null>(null);
  const projectRequested = useRef(false);
  const [parsed, setParsed] = useState<ParsedMidi | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [edits, setEdits] = useState<TrackEdit[]>([]);
  const [trackStates, setTrackStates] = useState<Record<number, TrackState>>({});
  const [fromBar, setFromBar] = useState(0);
  const [grid, setGrid] = useState<Grid>("beat");
  const [prefer, setPrefer] = useState<Prefer>("sharps");
  const [keyChoice, setKeyChoice] = useState<{ tonic: string; mode: string } | null>(null);
  const [handEdits, setHandEdits] = useState<HandEdits>(new Map());
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [segIdx, setSegIdx] = useState<number | null>(null);
  const [candIdx, setCandIdx] = useState(0);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [handFilter, setHandFilter] = useState<HandFilter>("both");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [audioProblem, setAudioProblem] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [dragging, setDragging] = useState(false);

  const stageRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const rollScroll = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<PianoAudio | null>(null);
  const run = useRef<{ startedAt: number; base: number; scheduledUntil: number; pbs: Playback[]; timer: number; raf: number } | null>(null);
  const audio = useCallback(() => (audioRef.current ??= new PianoAudio()), []);
  useEffect(() => setPrefs(loadPrefs(window.localStorage)), []);

  // ------------------------------------------------------------------ derived data
  const win: Window | null = useMemo(() => {
    if (!parsed) return null;
    try {
      return windowFrom(parsed, fromBar);
    } catch (e) {
      return null;
    }
  }, [parsed, fromBar]);
  useStickyScrollPadding(stageRef, Boolean(parsed && win));
  const editedNotes = useMemo(() => (parsed ? applyTrackEdits(parsed.notes, edits) : []), [parsed, edits]);
  const tracks = useMemo(() => (parsed ? summarizeTracks(parsed, edits) : []), [parsed, edits]);
  const trackHands = useMemo(() => Object.fromEntries(Object.entries(trackStates).map(([k, v]) => [Number(k), v.hand])), [trackStates]);
  const notesH: HandNote[] = useMemo(
    () => (analysis?.response.notes ? withHands(analysis.response.notes, analysis.ppq, analysis.windowStartTick, handEdits, trackHands) : []),
    [analysis, handEdits, trackHands],
  );
  const segments = analysis?.response.segments ?? [];
  const total = analysis ? totalSeconds(analysis.response) : 0;
  const pxPerSec = Math.min(60, Math.max(4, 6000 / Math.max(total, 1)));
  const rollView = useMemo(() => makeRollView(notesH, total, pxPerSec), [notesH, total, pxPerSec]);

  // What the server must be asked again about. Hand tags and hand edits are not in here: they
  // only change how notes are coloured, so changing them never costs a request.
  const serverKey = JSON.stringify([fromBar, edits, grid, prefer, keyChoice, tracks.map((t) => [t.index, trackStates[t.index]?.muted ?? false, trackStates[t.index]?.solo ?? false])]);

  // ------------------------------------------------------------------ playback
  const live = useRef({ notes: notesH, filter: handFilter, layers: prefs.layers, total });
  live.current = { notes: notesH, filter: handFilter, layers: prefs.layers, total };

  const stopPlayback = useCallback(() => {
    const r = run.current;
    if (r) {
      window.clearTimeout(r.timer);
      cancelAnimationFrame(r.raf);
      r.pbs.forEach((p) => p.stop());
      run.current = null;
    }
    audioRef.current?.allNotesOff();
    setPlaying(false);
  }, []);
  useEffect(() => stopPlayback, [stopPlayback]);

  const startPlayback = useCallback(
    async (from: number) => {
      const a = audio();
      if (!(await a.resume())) {
        setAudioProblem("This browser could not start sound. The notes are still shown.");
        return;
      }
      setAudioProblem(null);
      stopPlayback();
      const base = from >= live.current.total - 0.05 ? 0 : from;
      const r = { startedAt: performance.now(), base, scheduledUntil: base, pbs: [] as Playback[], timer: 0, raf: 0 };
      run.current = r;
      const clock = () => base + (performance.now() - r.startedAt) / 1000;
      // Notes are handed to the audio engine about a second ahead, a little at a time: it limits
      // how many voices it keeps when notes are scheduled, so scheduling a whole piece would cut
      // the early notes off.
      const pump = () => {
        if (run.current !== r) return;
        const { events, until } = pumpEvents(live.current.notes, r.scheduledUntil, clock(), live.current.filter);
        if (events.length) r.pbs.push(a.schedule(events, 60, live.current.layers));
        r.scheduledUntil = until;
        if (until < live.current.total + 1) r.timer = window.setTimeout(pump, PUMP_MS);
      };
      let lastShown = -1;
      const tick = () => {
        if (run.current !== r) return;
        const t = Math.max(base, clock() - AUDIO_LATENCY_SEC);
        if (t >= live.current.total + 0.15) {
          stopPlayback();
          setTime(0);
          return;
        }
        if (Math.abs(t - lastShown) > 0.03) {
          lastShown = t;
          setTime(t);
        }
        r.raf = requestAnimationFrame(tick);
      };
      setTime(base);
      setPlaying(true);
      pump();
      r.raf = requestAnimationFrame(tick);
    },
    [audio, stopPlayback],
  );

  // Changing which hand sounds carries on from the same place.
  const lastFilter = useRef(handFilter);
  useEffect(() => {
    if (lastFilter.current === handFilter) return;
    lastFilter.current = handFilter;
    if (run.current) void startPlayback(Math.max(0, time));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handFilter]);

  const sound = useCallback(
    async (notes: readonly number[], seconds: number) => {
      stopPlayback();
      if (!notes.length || !(await audio().resume())) return;
      audio().schedule([{ notes, start: 0, duration: seconds }], 60, prefs.layers);
    },
    [audio, prefs.layers, stopPlayback],
  );

  // ------------------------------------------------------------------ analysis
  const seq = useRef(0);
  const [retry, setRetry] = useState(0);
  const retries = useRef(0);
  const retryTimer = useRef(0);
  const lastKey = useRef("");
  useEffect(() => {
    if (!parsed || !win) return;
    if (lastKey.current !== serverKey) {
      lastKey.current = serverKey; // a new change, not a retry: start counting again
      retries.current = 0;
    }
    window.clearTimeout(retryTimer.current);
    const mine = ++seq.current;
    setBusy(true);
    const timer = window.setTimeout(() => {
      const names = Object.fromEntries(tracks.map((t) => [t.index, t.name]));
      let body;
      try {
        body = buildAnalyzeRequest(parsed, editedNotes, win, { grid, prefer, key: keyChoice, trackStates, trackNames: names });
      } catch (e) {
        if (mine === seq.current) {
          setBusy(false);
          setAnalyzeError(e instanceof StudioError ? e.message : "Could not prepare this section for analysis.");
        }
        return;
      }
      void analyzeMidi(body).then((r) => {
        if (mine !== seq.current) return; // a newer request replaced this one
        setBusy(false);
        if (r.ok) {
          retries.current = 0;
          setAnalysis({ response: r.data, windowStartTick: win.startTick, ppq: parsed.ppq });
          setAnalyzeError(null);
          setSegIdx(null);
          setCandIdx(0);
          stopPlayback();
          setTime(0);
        } else if (r.code === "rate_limited") {
          const advice = rateLimitAdvice(retries.current);
          setAnalyzeError(advice.message);
          if (advice.retry) {
            retries.current++;
            setBusy(true);
            retryTimer.current = window.setTimeout(() => setRetry((n) => n + 1), advice.delayMs);
          }
        } else setAnalyzeError(failureText(r));
      });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(retryTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed, serverKey, retry]);

  // ------------------------------------------------------------------ loading
  /** Shows a MIDI file. With `saved` settings (from My Library) they are put back as they were. */
  const loadBuffer = useCallback(
    async (buf: ArrayBuffer, name: string, saved?: unknown) => {
      stopPlayback();
      setLoadError(null);
      try {
        const p = parseMidi(buf);
        windowFrom(p, 0); // refuses a file whose very first bar is too dense, before anything else
        const restored = saved === undefined ? null : restoreMidiProject(saved, p);
        bytesRef.current = buf;
        setLoadCount((c) => c + 1);
        setParsed(p);
        setFileName(name);
        setEdits(restored?.edits ?? []);
        setTrackStates(restored?.trackStates ?? defaultStates(p));
        setFromBar(restored?.fromBar ?? 0);
        setHandEdits(restored?.handEdits ?? new Map());
        if (restored) {
          setGrid(restored.grid);
          setPrefer(restored.prefer);
        }
        setAnalysis(null);
        setAnalyzeError(null);
        setKeyChoice(restored?.keyChoice ?? null);
        setSegIdx(null);
        setSelectedKey(null);
        setTime(0);
      } catch (e) {
        bytesRef.current = null;
        setParsed(null);
        setAnalysis(null);
        setLoadError(e instanceof MidiError || e instanceof StudioError ? e.message : "This file could not be read.");
      }
    },
    [stopPlayback],
  );
  const load = useCallback(
    async (file: File) => {
      setProject(null); // a file chosen by hand is a new piece of work, not the saved project
      await loadBuffer(await file.arrayBuffer(), file.name);
    },
    [loadBuffer],
  );

  // A project opened from My Library: fetch its file and settings, then show them.
  useEffect(() => {
    if (!projectId || projectRequested.current) return; // strict mode runs effects twice in development
    projectRequested.current = true;
    void (async () => {
      const [item, file] = await Promise.all([getItem(projectId), getItemFile(projectId)]);
      if (!item.ok || !file.ok) {
        setLoadError(!item.ok ? item.message : "The saved file could not be loaded.");
      } else {
        setProject({ id: item.data.id, title: item.data.title });
        await loadBuffer(file.data, item.data.file_name ?? `${item.data.title}.mid`, item.data.data);
      }
      setProjectLoading(false);
    })();
  }, [projectId, loadBuffer]);
  const loadExample = async () => {
    const res = await fetch("/examples/c-am-f-g.mid");
    if (!res.ok) return setLoadError("The example could not be loaded.");
    await load(new File([await res.arrayBuffer()], "C - Am - F - G7 (example).mid"));
  };

  // ------------------------------------------------------------------ what the keyboard shows
  const seg = segIdx !== null ? (segments[segIdx] ?? null) : null;
  const chosenSeg = useMemo(() => {
    if (!seg || candIdx === 0 || !seg.candidates[candIdx]) return seg;
    return { ...seg, candidates: [seg.candidates[candIdx], ...seg.candidates.filter((_, i) => i !== candIdx)] };
  }, [seg, candIdx]);
  const selectedNote = notesH.find((n) => n.key === selectedKey) ?? null;
  const sounding: HandNote[] = playing
    ? notesSounding(notesH, time)
    : seg
      ? notesH.filter((n) => n.start_sec < seg.end_sec && n.end_sec > seg.start_sec)
      : selectedNote
        ? [selectedNote]
        : [];
  const momentSeg = playing ? segmentAt(segments, time) : chosenSeg;
  const overlay = useMemo(() => overlayForMoment(sounding, momentSeg), [sounding.map((n) => n.key).join("|"), momentSeg]); // eslint-disable-line react-hooks/exhaustive-deps
  const playingIdx = playing ? segments.findIndex((s) => s.start_sec <= time && time < s.end_sec) : -1;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !overlay) return;
    const xs = [...overlay.marks.keys()].map((m) => keyFor(m)?.x ?? 0);
    if (!xs.length) return;
    const lo = Math.min(...xs) * prefs.keyWidth;
    const hi = (Math.max(...xs) + 1) * prefs.keyWidth;
    if (lo < el.scrollLeft || hi > el.scrollLeft + el.clientWidth) el.scrollLeft = Math.max(0, (lo + hi) / 2 - el.clientWidth / 2);
  }, [overlay, prefs.keyWidth]);

  // When a file is first analysed, start the keyboard around the music rather than at the bass end.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !analysis?.response.notes?.length) return;
    const pitches = analysis.response.notes.map((n) => n.midi);
    const k = keyFor(Math.round((Math.min(...pitches) + Math.max(...pitches)) / 2));
    if (k) el.scrollLeft = Math.max(0, (k.x + 0.5) * prefs.keyWidth - el.clientWidth / 2);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis]);

  // keep the playhead in view in the roll
  useEffect(() => {
    const el = rollScroll.current;
    if (!el || !playing) return;
    const x = rollX(rollView, time);
    if (x < el.scrollLeft + 40 || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, x - 80);
  }, [time, playing, rollView]);

  // ------------------------------------------------------------------ actions
  const setHand = (n: HandNote, hand: Hand) => setHandEdits((m) => new Map(m).set(n.key, hand));
  const resetHand = (n: HandNote) =>
    setHandEdits((m) => {
      const next = new Map(m);
      next.delete(n.key);
      return next;
    });
  const seek = (sec: number) => {
    setSelectedKey(null);
    const i = segments.findIndex((s) => s.start_sec <= sec && sec < s.end_sec);
    if (playing) void startPlayback(sec);
    else {
      setTime(sec);
      setSegIdx(i >= 0 ? i : null);
      setCandIdx(0);
    }
  };
  const patchTrack = (track: number, patch: Partial<TrackState>) => setTrackStates((s) => ({ ...s, [track]: { ...(s[track] ?? { hand: null, muted: false, solo: false }), ...patch } }));
  const addEdit = (e: TrackEdit) => {
    if (!parsed) return;
    try {
      applyTrackEdits(parsed.notes, [...edits, e]);
      setEdits((x) => [...x, e]);
      if (e.type === "split") setTrackStates((s) => ({ ...s, [e.into]: { hand: null, muted: false, solo: false } }));
    } catch (err) {
      setAnalyzeError(err instanceof StudioError ? err.message : "That change could not be made.");
    }
  };
  const goWindow = (direction: 1 | -1) => {
    if (!parsed || !win) return;
    const n = neighbour(parsed, win, direction);
    if (n) setFromBar(n.fromBar);
  };

  const response = analysis?.response ?? null;
  const key = response?.key ?? null;

  // ------------------------------------------------------------------ view
  return (
    <div className="space-y-6">
      <section
        aria-label="Open a MIDI file"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f) void load(f);
        }}
        className={`${card} ${dragging ? "border-accent bg-accent-soft" : ""}`}
      >
        <div className="flex flex-wrap items-center gap-3">
          <label className={`${buttonStyles()} cursor-pointer`}>
            <Upload aria-hidden className="h-4 w-4" /> Choose a MIDI file
            <input
              type="file"
              accept=".mid,.midi,audio/midi,audio/x-midi"
              className="sr-only"
              data-testid="midi-file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void load(f);
                e.target.value = "";
              }}
            />
          </label>
          <button type="button" onClick={() => void loadExample()} className={buttonStyles({ variant: "secondary" })}>
            <FileMusic aria-hidden className="h-4 w-4" /> Try an example
          </button>
          <span className="text-sm text-muted">or drop a .mid file here</span>
        </div>
        <p className="mt-3 text-xs text-muted">The file is read on your device. Only the notes and timing are sent to be analysed. Nothing is kept unless you choose Save to My Library.</p>
        {loadError ? <div className="mt-3"><Notice tone="error">{loadError}</Notice></div> : null}
        {projectLoading ? <div className="mt-3"><Notice>Opening your saved project…</Notice></div> : null}
      </section>

      {parsed && win ? (
        <>
          <section aria-label="File" className={card}>
            <h2 className="text-base font-semibold">{fileName}</h2>
            <p className="mt-1 text-sm text-muted">
              Format {parsed.format} · {parsed.notes.length.toLocaleString()} notes · {win.totalBars} bars · {parsed.ppq} ticks per beat ·{" "}
              {parsed.tempoChanges.length ? `${Math.round(parsed.tempoChanges[0]!.bpm)} BPM${parsed.tempoChanges.length > 1 ? " (changes)" : ""}` : "no tempo given (120 BPM assumed)"} ·{" "}
              {parsed.timeSignatures.length ? `${parsed.timeSignatures[0]!.numerator}/${parsed.timeSignatures[0]!.denominator}${parsed.timeSignatures.length > 1 ? " (changes)" : ""}` : "no time signature given (4/4 assumed)"}
            </p>
            {parsed.warnings.length ? (
              <details className="mt-2 text-sm text-muted">
                <summary className="cursor-pointer">{parsed.warnings.length} note{parsed.warnings.length === 1 ? "" : "s"} about this file</summary>
                <ul className="mt-1 list-disc space-y-0.5 pl-5">{parsed.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </details>
            ) : null}
            {!win.whole ? (
              <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Section being analysed">
                <Notice>This file has more notes than can be analysed at once, so it is analysed in sections. Showing bars {win.fromBar + 1} to {win.toBar} of {win.totalBars}.</Notice>
                <button type="button" onClick={() => goWindow(-1)} disabled={win.fromBar === 0} className={buttonStyles({ variant: "secondary" })}>Earlier section</button>
                <button type="button" onClick={() => goWindow(1)} disabled={win.toBar >= win.totalBars} className={buttonStyles({ variant: "secondary" })}>Later section</button>
              </div>
            ) : null}
          </section>

          <div ref={stageRef} className="sticky top-[3.6rem] z-10 lg:top-2 [@media(max-height:620px)]:static">
            <div className="rounded-xl border border-line bg-surface p-3 shadow-md">
              <div className="mb-2.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="min-h-9 text-sm" aria-live="polite">
                  {overlay?.title ? (
                    <span><span className="text-muted">{playing ? "Playing " : "Showing "}</span><span className="font-semibold">{prettyNote(overlay.title)}</span></span>
                  ) : (
                    <span className="text-muted">{playing ? "Playing" : "Choose a chord or a note to see it on the keys."}</span>
                  )}
                  <span className="ml-3 text-muted">{formatTime(time, true)} / {formatTime(total)}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" disabled={!response || busy} onClick={() => (playing ? stopPlayback() : void startPlayback(time))} className={buttonStyles({ variant: "primary" })}>
                    {playing ? <Pause aria-hidden className="h-4 w-4" /> : <Play aria-hidden className="h-4 w-4" />}
                    {playing ? "Stop" : "Play"}
                  </button>
                  <select aria-label="Which hand to hear" className={`${selectClass} w-44`} value={handFilter} onChange={(e) => setHandFilter(e.target.value as HandFilter)}>
                    {HAND_FILTERS.map((h) => <option key={h.value} value={h.value}>{h.label}</option>)}
                  </select>
                </div>
              </div>
              <PianoKeyboard
                keyWidth={prefs.keyWidth}
                held={new Set()}
                overlay={overlay}
                labels={{ mode: prefs.labels, accidentals: prefs.accidentals, middleC: prefs.middleC, unicode: prefs.unicode }}
                scrollRef={scrollRef}
                onKeyDown={(n, v) => void audio().resume().then(() => audio().noteOn(n, v, prefs.layers))}
                onKeyUp={(n) => audio().noteOff(n)}
              />
              <ul className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted" aria-label="What the colours mean">
                <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-4 bg-hand-left" /> Left hand</li>
                <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-4 bg-hand-right" /> Right hand</li>
                <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-dot bg-dot" /> Chord root</li>
                <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-dot bg-dot-soft" /> Chord tone</li>
                <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-dashed border-muted" /> Extra note</li>
              </ul>
            </div>
          </div>

          {audioProblem ? <Notice tone="error">{audioProblem}</Notice> : null}
          {analyzeError ? <Notice tone="error">{analyzeError}</Notice> : null}
          {busy ? <p className="text-sm text-muted" role="status">Analysing…</p> : null}

          {response ? (
            <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <div className="min-w-0 space-y-6">
                <section aria-label="Notes and chords" className={card}>
                  <h2 className="mb-2 text-base font-semibold">Notes and chords</h2>
                  <p className="mb-2 text-xs text-muted">
                    Lighter notes are the Studio&apos;s guess of the hand; solid ones were set by you or by a track you assigned. Click a note to choose it, click empty space to move the playhead.
                  </p>
                  <div ref={rollScroll} className="relative overflow-x-auto pb-2" data-testid="roll-scroll">
                    <div className="relative" style={{ width: rollWidth(rollView) }}>
                      <div className="mb-1"><ChordTimeline segments={segments} selected={segIdx} current={playingIdx >= 0 ? playingIdx : null} pxPerSec={rollView.pxPerSec} onSelect={(i) => { setSelectedKey(null); setSegIdx(i); setCandIdx(0); if (playing) stopPlayback(); }} /></div>
                      <div className="relative">
                        <PianoRoll
                          notes={notesH}
                          view={rollView}
                          selectedKey={selectedKey}
                          onSelect={(n) => { setSelectedKey(n?.key ?? null); if (n) setSegIdx(null); }}
                          onSeek={seek}
                          onSetHand={setHand}
                          onAudition={(n) => void sound([n.midi], 1)}
                        />
                        <div aria-hidden className="pointer-events-none absolute top-0 h-full w-0.5 bg-accent" style={{ left: rollX(rollView, time) }} data-testid="playhead" />
                      </div>
                    </div>
                  </div>
                </section>

                {selectedNote ? (
                  <section aria-label="Selected note" className={card}>
                    <h2 className="text-base font-semibold">Note {selectedNote.name}</h2>
                    <p className="mt-1 text-sm text-muted">
                      {formatTime(selectedNote.start_sec, true)} · track {selectedNote.track + 1} · played with{" "}
                      {selectedNote.hand === "L" ? "the left hand" : selectedNote.hand === "R" ? "the right hand" : "no hand set"}
                      {selectedNote.handSource === "auto" ? " (the Studio's guess)" : selectedNote.handSource === "track" ? " (from its track)" : " (set by you)"}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button type="button" aria-pressed={selectedNote.hand === "L"} onClick={() => setHand(selectedNote, "L")} className={buttonStyles({ variant: selectedNote.hand === "L" ? "primary" : "secondary" })}>Left hand</button>
                      <button type="button" aria-pressed={selectedNote.hand === "R"} onClick={() => setHand(selectedNote, "R")} className={buttonStyles({ variant: selectedNote.hand === "R" ? "primary" : "secondary" })}>Right hand</button>
                      <button type="button" onClick={() => setHand(selectedNote, flipHand(selectedNote.hand))} className={buttonStyles({ variant: "ghost" })}>Swap</button>
                      {selectedNote.handSource === "user" ? <button type="button" onClick={() => resetHand(selectedNote)} className={buttonStyles({ variant: "ghost" })}>Back to guess</button> : null}
                      <button type="button" onClick={() => void sound([selectedNote.midi], 1)} className={buttonStyles({ variant: "secondary" })}>Hear it</button>
                    </div>
                  </section>
                ) : null}

                {seg ? (
                  <SegmentDetails
                    segment={seg}
                    candidate={candIdx}
                    onCandidate={setCandIdx}
                    onHear={() => void sound([...new Set(seg.pitches)], 2)}
                    onPlayFrom={() => void startPlayback(seg.start_sec)}
                  />
                ) : null}
              </div>

              <div className="min-w-0 space-y-6">
                <TrackPanel
                  tracks={tracks}
                  states={trackStates}
                  changeCount={edits.length}
                  canSplit={freeTrack(parsed, edits) !== null}
                  onState={patchTrack}
                  onMerge={(from, into) => addEdit({ type: "merge", from: [from], into })}
                  onSplit={(track, pitch) => {
                    const into = freeTrack(parsed, edits);
                    if (into !== null) addEdit({ type: "split", track, pitch, into });
                  }}
                  onUndo={() => setEdits((e) => e.slice(0, -1))}
                  onReset={() => setEdits([])}
                />

                <div className={card}>
                  <h2 className="mb-1 text-lg font-bold">My Library</h2>
                  <p className="mb-3 text-sm text-muted">Keep this file with your track edits, hand choices and key, and carry on later.</p>
                  <SaveToLibrary
                    key={`${project?.id ?? "new"}-${loadCount}`}
                    kind="midi"
                    defaultTitle={(fileName ?? "MIDI project").replace(/\.midi?$/i, "")}
                    existing={project}
                    disabled={!bytesRef.current}
                    build={() => ({
                      data: serializeMidiProject({ edits, trackStates, fromBar, grid, prefer, keyChoice, handEdits }),
                      fileName: fileName ?? "project.mid",
                      fileBytes: bytesRef.current ?? undefined,
                    })}
                  />
                </div>

                <ExportPanel
                  parsed={parsed}
                  fileName={fileName}
                  edits={edits}
                  trackStates={trackStates}
                  handEdits={handEdits}
                  keyChoice={keyChoice}
                  grid={grid}
                  prefer={prefer}
                  onRestore={(c) => {
                    setEdits(c.edits);
                    setTrackStates(c.trackStates);
                    setHandEdits(new Map(c.handEdits));
                    setKeyChoice(c.key);
                    setGrid(c.grid);
                    setPrefer(c.prefer);
                  }}
                />

                <section aria-label="Key and settings" className={`${card} space-y-4`}>
                  <div>
                    <h2 className="text-base font-semibold">Key</h2>
                    {key ? (
                      <p className="mt-1 text-sm">
                        <span className="font-semibold">{prettyNote(key.name)}</span> <span className="text-muted">({key.signature})</span>
                        <span className="ml-1 rounded bg-surface-2 px-1.5 py-0.5 text-xs text-muted">{response.key_source === "estimated" ? "estimated" : "chosen by you"}</span>
                      </p>
                    ) : (
                      <p className="mt-1 text-sm text-muted">No key could be estimated, so there are no Roman numerals.</p>
                    )}
                    {response.key_source === "estimated" ? (
                      <div className="mt-2 text-sm text-muted">
                        {response.key_estimate.ambiguous ? <p className="mb-1 text-fg">Another key is nearly as likely, so treat this as a guess.</p> : null}
                        <ul className="space-y-0.5">{response.key_estimate.candidates.slice(0, 3).map((c) => <li key={c.key.name}>{prettyNote(c.key.name)}</li>)}</ul>
                        <p className="mt-1 text-xs">Candidates are ranked, not given probabilities.</p>
                        {response.key_estimate.warnings.map((w) => <p key={w} className="mt-1 text-xs">{w}</p>)}
                      </div>
                    ) : null}
                  </div>
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
                      </span>
                    </label>
                    <label className="block text-sm"><span className="mb-1.5 block font-medium">Chords every</span>
                      <select className={selectClass} value={grid} onChange={(e) => setGrid(e.target.value as Grid)}>
                        <option value="beat">beat</option>
                        <option value="half_bar">half bar</option>
                        <option value="bar">bar</option>
                      </select>
                    </label>
                    <label className="block text-sm"><span className="mb-1.5 block font-medium">Spelling</span>
                      <select className={selectClass} value={prefer} onChange={(e) => setPrefer(e.target.value as Prefer)}>
                        <option value="sharps">Sharps</option>
                        <option value="flats">Flats</option>
                      </select>
                    </label>
                  </div>
                </section>

                {response.warnings.length ? (
                  <Notice>{response.warnings.slice(0, 3).join(" ")}{response.warnings.length > 3 ? ` (and ${response.warnings.length - 3} more)` : ""}</Notice>
                ) : null}
                <p className="text-xs text-muted">
                  Chord and key results are estimates made from the notes, not certainties. A chord built from known MIDI notes is more reliable than one heard in audio, but a few notes can still fit more than one chord.
                </p>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
