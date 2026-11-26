"use client";

import { ChevronLeft, ChevronRight, Piano } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { PianoAudio } from "@/lib/piano/audio";
import { COMPUTER_BASE_CHOICES, midiForCode, shouldIgnoreKeyEvent, spaceBelongsToControl } from "@/lib/piano/computerKeys";
import { EMPTY_HELD, type Held, type Source, heldNotes, isHeld, press, release } from "@/lib/piano/heldNotes";
import type { Overlay } from "@/lib/piano/highlight";
import { type LabelMode, WHITE_COUNT, keyFor } from "@/lib/piano/keys";
import { type MidiStatus, connectMidi } from "@/lib/piano/midiInput";
import { useStickyScrollPadding } from "@/lib/useStickyScrollPadding";
import { DEFAULT_PREFS, KEY_WIDTH_MAX, KEY_WIDTH_MIN, type Prefs, STORAGE_KEY, loadPrefs, savePrefs } from "@/lib/piano/prefs";
import { ChordPanel } from "./ChordPanel";
import { type HeardSummary, IdentifyPanel } from "./IdentifyPanel";
import { KeyboardOverview } from "./KeyboardOverview";
import { PianoKeyboard } from "./PianoKeyboard";
import { ScalePanel } from "./ScalePanel";
import { SoundPanel } from "./SoundPanel";
import { Labelled, prettyNote, selectClass } from "./shared";

type Tab = "chord" | "scale" | "identify";
const TABS: { id: Tab; label: string }[] = [
  { id: "chord", label: "Chord" },
  { id: "scale", label: "Scale" },
  { id: "identify", label: "What am I playing?" },
];
const LABEL_CHOICES: { value: LabelMode; label: string }[] = [
  { value: "c", label: "C keys with octave" },
  { value: "names", label: "All note names" },
  { value: "names-octave", label: "Names with octave" },
  { value: "none", label: "No labels" },
];
const MIDDLE_C_NOTE = 60;

type Step = { notes: number[]; at: number; dur: number };

export function PianoWorkspace() {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [loaded, setLoaded] = useState(false);
  const [held, setHeld] = useState<Held>(EMPTY_HELD);
  const [tab, setTab] = useState<Tab>("chord");
  const [overlays, setOverlays] = useState<Record<Tab, Overlay | null>>({ chord: null, scale: null, identify: null });
  const [lastChord, setLastChord] = useState<number[]>([]);
  const [sustainButton, setSustainButton] = useState(false);
  const [pedalKey, setPedalKey] = useState(false);
  const [pedalMidi, setPedalMidi] = useState(false);
  const [audioProblem, setAudioProblem] = useState(false);
  const [midi, setMidi] = useState<MidiStatus | null>(null);
  const [heard, setHeard] = useState<HeardSummary | null>(null);

  const audioRef = useRef<PianoAudio | null>(null);
  const heldRef = useRef<Held>(EMPTY_HELD);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const stageRef = useRef<HTMLDivElement | null>(null);
  useStickyScrollPadding(stageRef, true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const centerRef = useRef((keyFor(MIDDLE_C_NOTE)?.x ?? 23) / WHITE_COUNT);
  const timers = useRef<number[]>([]);
  const stopProgram = useRef<(() => void) | null>(null);
  const programNotes = useRef(new Set<number>());
  const codesDown = useRef(new Map<string, number>());
  const midiCleanup = useRef<(() => void) | null>(null);

  const audio = useCallback(() => (audioRef.current ??= new PianoAudio()), []);

  // ---- preferences (read after mount so the first render matches the server's)
  useEffect(() => {
    const stored = loadPrefs(window.localStorage);
    // First visit on a phone: smaller keys so more of the keyboard fits.
    const firstVisit = window.localStorage.getItem(STORAGE_KEY) === null;
    setPrefs(firstVisit && window.innerWidth < 640 ? { ...stored, keyWidth: 30 } : stored);
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (loaded) savePrefs(window.localStorage, prefs);
  }, [loaded, prefs]);
  const update = (patch: Partial<Prefs>) => setPrefs((p) => ({ ...p, ...patch }));

  useEffect(() => {
    audio().setVolume(prefs.volume);
    audio().setTuning(prefs.a4);
  }, [audio, prefs.volume, prefs.a4]);

  const sustain = sustainButton || pedalKey || pedalMidi;
  useEffect(() => audio().setSustain(sustain), [audio, sustain]);

  // ---- notes
  const changeHeld = useCallback((fn: (h: Held) => Held) => {
    heldRef.current = fn(heldRef.current);
    setHeld(heldRef.current);
  }, []);

  const pressNote = useCallback(
    (note: number, velocity: number, source: Source) => {
      const a = audio();
      void a.resume().then((ok) => {
        if (!ok) setAudioProblem(true);
      });
      if (!isHeld(heldRef.current, note)) a.noteOn(note, velocity, prefsRef.current.layers);
      changeHeld((h) => press(h, note, source));
    },
    [audio, changeHeld],
  );

  const releaseNote = useCallback(
    (note: number, source: Source) => {
      const next = release(heldRef.current, note, source);
      if (next === heldRef.current) return;
      changeHeld(() => next);
      if (!isHeld(next, note)) audio().noteOff(note);
    },
    [audio, changeHeld],
  );

  const releaseEverything = useCallback(() => {
    audio().allNotesOff();
    codesDown.current.clear();
    programNotes.current.clear();
    changeHeld(() => EMPTY_HELD);
  }, [audio, changeHeld]);

  // The identify panel works on the last keys played together, kept after they are released.
  const previous = useRef<number[]>([]);
  useEffect(() => {
    const now = heldNotes(held);
    if (now.some((n) => !previous.current.includes(n))) setLastChord(now);
    previous.current = now;
  }, [held]);

  // ---- computer keyboard
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const plain = { ctrlKey: e.ctrlKey, metaKey: e.metaKey, altKey: e.altKey, repeat: e.repeat, target: e.target };
      if (e.code === "Space") {
        // Hold Space for the sustain pedal, unless Space is meant for a focused control.
        if (!shouldIgnoreKeyEvent({ ...plain, repeat: false }) && !spaceBelongsToControl(e.target)) {
          e.preventDefault();
          setPedalKey(true);
        }
        return;
      }
      if (shouldIgnoreKeyEvent(plain)) return;
      const note = midiForCode(e.code, prefsRef.current.computerBase);
      if (note === null || codesDown.current.has(e.code)) return;
      e.preventDefault();
      codesDown.current.set(e.code, note);
      pressNote(note, 90, "keyboard");
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space") setPedalKey(false);
      const note = codesDown.current.get(e.code);
      if (note === undefined) return;
      codesDown.current.delete(e.code);
      releaseNote(note, "keyboard");
    };
    const blur = () => {
      setPedalKey(false);
      releaseEverything();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, [pressNote, releaseNote, releaseEverything]);

  // ---- MIDI keyboard
  const startMidi = async () => {
    midiCleanup.current?.();
    midiCleanup.current = await connectMidi({
      onStatus: setMidi,
      onMessage: (m) => {
        if (m.type === "on") pressNote(m.note, m.velocity, "midi");
        else if (m.type === "off") releaseNote(m.note, "midi");
        else if (m.type === "sustain") setPedalMidi(m.on);
      },
    });
  };

  // ---- playing chords and scales from the panels, with the keys pressing in time
  const cancelProgram = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
    stopProgram.current?.();
    stopProgram.current = null;
    for (const n of programNotes.current) changeHeld((h) => release(h, n, "program"));
    programNotes.current.clear();
  }, [changeHeld]);

  const playSteps = useCallback(
    (steps: Step[]) => {
      cancelProgram();
      const a = audio();
      void a.resume().then((ok) => {
        if (!ok) {
          setAudioProblem(true);
          return;
        }
        // Tempo 60 makes one beat one second, so step times are in seconds.
        const playback = a.schedule(steps.map((s) => ({ notes: s.notes, start: s.at, duration: s.dur })), 60, prefsRef.current.layers);
        stopProgram.current = playback.stop;
        for (const s of steps) {
          timers.current.push(
            window.setTimeout(() => {
              for (const n of s.notes) {
                programNotes.current.add(n);
                changeHeld((h) => press(h, n, "program"));
              }
            }, s.at * 1000),
            window.setTimeout(() => {
              for (const n of s.notes) {
                programNotes.current.delete(n);
                changeHeld((h) => release(h, n, "program"));
              }
            }, (s.at + s.dur) * 1000),
          );
        }
      });
    },
    [audio, cancelProgram, changeHeld],
  );

  const playChord = useCallback((notes: number[]) => playSteps([{ notes, at: 0, dur: 1.6 }]), [playSteps]);
  const playScale = useCallback((notes: number[]) => playSteps(notes.map((n, i) => ({ notes: [n], at: i * 0.4, dur: 0.38 }))), [playSteps]);

  useEffect(
    () => () => {
      timers.current.forEach((t) => window.clearTimeout(t));
      stopProgram.current?.();
      audioRef.current?.allNotesOff();
      midiCleanup.current?.();
    },
    [],
  );

  // ---- scrolling
  const scrollEl = () => scrollRef.current;
  useEffect(() => {
    const el = scrollEl();
    if (!el) return;
    const onScroll = () => {
      centerRef.current = (el.scrollLeft + el.clientWidth / 2) / (WHITE_COUNT * prefsRef.current.keyWidth);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    const el = scrollEl();
    if (el) el.scrollLeft = centerRef.current * WHITE_COUNT * prefs.keyWidth - el.clientWidth / 2;
  }, [prefs.keyWidth, loaded]);
  const scrollBy = (octaves: number) => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scrollEl()?.scrollBy({ left: octaves * 7 * prefs.keyWidth, behavior: reduce ? "auto" : "smooth" });
  };
  const goToMiddleC = () => {
    const el = scrollEl();
    const x = keyFor(MIDDLE_C_NOTE)?.x ?? 23;
    if (el) el.scrollLeft = (x + 0.5) * prefs.keyWidth - el.clientWidth / 2;
  };

  // ---- what the keyboard shows
  const overlay = overlays[tab];
  const heldSet = useMemo(() => new Set(held.keys()), [held]);
  const hasHands = useMemo(() => [...(overlay?.marks.values() ?? [])].some((m) => m.hand), [overlay]);
  const hasBass = useMemo(() => [...(overlay?.marks.values() ?? [])].some((m) => m.bass), [overlay]);
  const hasExtra = useMemo(() => [...(overlay?.marks.values() ?? [])].some((m) => m.role === "extra"), [overlay]);

  const setOverlay = (which: Tab) => (o: Overlay | null) => setOverlays((s) => (s[which] === o ? s : { ...s, [which]: o }));
  const setChord = useMemo(() => setOverlay("chord"), []);
  const setScale = useMemo(() => setOverlay("scale"), []);
  const setIdentify = useMemo(() => setOverlay("identify"), []);

  const onTabKey = (e: React.KeyboardEvent, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = TABS[(i + step + TABS.length) % TABS.length];
    if (next) {
      setTab(next.id);
      document.getElementById(`tab-${next.id}`)?.focus();
    }
  };

  const heardText =
    heard === null
      ? null
      : heard.symbol === null
        ? "no clear chord"
        : `${prettyNote(heard.symbol)}${heard.others.length ? `, or ${heard.others.map(prettyNote).join(" / ")}` : ""}`;

  return (
    <div className="space-y-6">
      {/* The stage stays in view while the panels below are used, so every change shows on the keys. */}
      <div ref={stageRef} className="sticky top-[3.6rem] z-10 lg:top-2 [@media(max-height:620px)]:static">
        <div className="rounded-xl border border-line bg-surface p-3 shadow-md">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <div className="flex min-h-9 min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-sm" aria-live="polite">
              {overlay ? (
                <span>
                  <span className="text-muted">Showing </span>
                  <span className="font-semibold">{prettyNote(overlay.title)}</span>
                </span>
              ) : null}
              {heardText ? (
                <span>
                  <span className="text-muted">You played </span>
                  <span className="font-semibold">{heardText}</span>
                </span>
              ) : null}
              {!overlay && !heardText ? <span className="text-muted">Play a key, or choose a chord below.</span> : null}
            </div>
            <div className="flex items-center">
              <button type="button" onClick={() => scrollBy(-1)} aria-label="Move the keyboard down one octave" className={buttonStyles({ variant: "ghost" })}>
                <ChevronLeft aria-hidden className="h-4 w-4" />
              </button>
              <button type="button" onClick={goToMiddleC} className={buttonStyles({ variant: "ghost" })}>
                Middle C
              </button>
              <button type="button" onClick={() => scrollBy(1)} aria-label="Move the keyboard up one octave" className={buttonStyles({ variant: "ghost" })}>
                <ChevronRight aria-hidden className="h-4 w-4" />
              </button>
            </div>
          </div>

          <PianoKeyboard
            keyWidth={prefs.keyWidth}
            held={heldSet}
            overlay={overlay}
            labels={{ mode: prefs.labels, accidentals: prefs.accidentals, middleC: prefs.middleC, unicode: prefs.unicode }}
            scrollRef={scrollRef}
            onKeyDown={(n, v) => pressNote(n, v, "pointer")}
            onKeyUp={(n) => releaseNote(n, "pointer")}
          />
          <KeyboardOverview scrollRef={scrollRef} keyWidth={prefs.keyWidth} marks={overlay?.marks} held={heldSet} />

          {overlay ? (
            <ul className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted" aria-label="What the marks on the keys mean">
              <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-key-white bg-dot ring-1 ring-line" /> Root</li>
              <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-dot bg-dot-soft" /> {overlay.source === "scale" ? "Scale note" : "Chord tone"}</li>
              {hasExtra ? <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-dashed border-muted bg-key-white" /> Extra note</li> : null}
              {hasBass ? <li className="flex items-center gap-1.5"><span aria-hidden className="h-3.5 w-3.5 rounded-sm border-2 border-dot bg-dot-soft" /> Bass note (square)</li> : null}
              {hasHands ? (
                <>
                  <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-4 bg-hand-left" /> Left hand</li>
                  <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-4 bg-hand-right" /> Right hand</li>
                </>
              ) : null}
            </ul>
          ) : null}
        </div>
      </div>

      <Card title="Keyboard settings">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Labelled label="Key labels">
            <select className={selectClass} value={prefs.labels} onChange={(e) => update({ labels: e.target.value as LabelMode })}>
              {LABEL_CHOICES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Labelled>
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">Black keys are</legend>
            <div className="flex gap-1.5">
              {(["sharps", "flats"] as const).map((a) => (
                <button
                  key={a}
                  type="button"
                  aria-pressed={prefs.accidentals === a}
                  onClick={() => update({ accidentals: a })}
                  className={`min-h-11 flex-1 rounded-lg border px-3 text-sm font-semibold ${prefs.accidentals === a ? "border-accent bg-accent text-accent-fg" : "border-line bg-surface hover:bg-surface-2"}`}
                >
                  {a === "sharps" ? "Sharps ♯" : "Flats ♭"}
                </button>
              ))}
            </div>
          </fieldset>
          <label className="block text-sm lg:col-span-2">
            <span className="mb-1.5 block font-medium">Key size</span>
            <input
              type="range"
              min={KEY_WIDTH_MIN}
              max={KEY_WIDTH_MAX}
              value={prefs.keyWidth}
              onChange={(e) => update({ keyWidth: Number(e.target.value) })}
              className="min-h-11 w-full accent-[rgb(var(--c-accent))]"
            />
          </label>
        </div>

        <p className="mt-3 max-w-[70ch] text-sm text-muted">
          Play with the mouse or touch (slide across keys for a glissando; press lower on a key for a louder note), the computer keyboard (rows Z–M and Q–P), or a MIDI keyboard.
        </p>
        {audioProblem ? (
          <div className="mt-3">
            <Notice tone="error">This browser cannot play sound, or sound is blocked for this page. Check the browser's site settings and try again. The keys and theory still work.</Notice>
          </div>
        ) : null}

        <details className="mt-4 rounded-lg border border-line px-4 py-2">
          <summary className="min-h-11 cursor-pointer text-sm font-semibold leading-[2.75rem]">More options</summary>
          <div className="grid gap-4 pb-3 sm:grid-cols-2 lg:grid-cols-4">
            <Labelled label="Middle C is called" hint="Octave numbering differs between programs.">
              <select className={selectClass} value={prefs.middleC} onChange={(e) => update({ middleC: Number(e.target.value) as 3 | 4 | 5 })}>
                <option value={4}>C4 (scientific pitch)</option>
                <option value={3}>C3 (Yamaha, Logic)</option>
                <option value={5}>C5</option>
              </select>
            </Labelled>
            <Labelled label="Tuning (A4)">
              <select className={selectClass} value={prefs.a4} onChange={(e) => update({ a4: Number(e.target.value) })}>
                {[415, 432, 440, 442, 444].map((f) => (
                  <option key={f} value={f}>
                    {f} Hz{f === 440 ? " (standard)" : ""}
                  </option>
                ))}
              </select>
            </Labelled>
            <Labelled label="Computer keys start at">
              <select className={selectClass} value={prefs.computerBase} onChange={(e) => update({ computerBase: Number(e.target.value) })}>
                {COMPUTER_BASE_CHOICES.map((m) => (
                  <option key={m} value={m}>
                    {m === 36 ? "C2" : m === 48 ? "C3" : "C4"}
                  </option>
                ))}
              </select>
            </Labelled>
            <div className="text-sm">
              <span className="mb-1.5 block font-medium">MIDI keyboard</span>
              <button type="button" onClick={() => void startMidi()} className={buttonStyles({ variant: "secondary" })}>
                <Piano aria-hidden className="h-4 w-4" /> Connect
              </button>
              <p className="mt-1 text-xs text-muted" role="status">
                {midi === null ? "Works in Chrome and Edge." : midi.state === "unsupported" ? "This browser does not support MIDI keyboards." : midi.state === "denied" ? "Permission was refused. Allow MIDI in the browser's site settings." : midi.devices.length ? `Listening to ${midi.devices.join(", ")}.` : "No MIDI keyboard found. Plug one in."}
              </p>
            </div>
          </div>
        </details>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card title="Theory on the keys">
          <div role="tablist" aria-label="Theory tools" className="mb-5 flex flex-wrap gap-1 border-b border-line">
            {TABS.map((t, i) => (
              <button
                key={t.id}
                id={`tab-${t.id}`}
                role="tab"
                type="button"
                aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => setTab(t.id)}
                onKeyDown={(e) => onTabKey(e, i)}
                className={`-mb-px min-h-11 border-b-2 px-4 text-sm font-semibold ${tab === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"}`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div id="panel-chord" role="tabpanel" aria-labelledby="tab-chord" hidden={tab !== "chord"}>
            <ChordPanel active={tab === "chord"} onOverlay={setChord} onPlay={playChord} />
          </div>
          <div id="panel-scale" role="tabpanel" aria-labelledby="tab-scale" hidden={tab !== "scale"}>
            <ScalePanel active={tab === "scale"} onOverlay={setScale} onPlaySequence={playScale} />
          </div>
          <div id="panel-identify" role="tabpanel" aria-labelledby="tab-identify" hidden={tab !== "identify"}>
            <IdentifyPanel
              active={tab === "identify"}
              notes={lastChord}
              accidentals={prefs.accidentals}
              onOverlay={setIdentify}
              onSummary={setHeard}
              onClear={() => setLastChord([])}
            />
          </div>
        </Card>

        <Card title="Sound">
          <SoundPanel
            layers={prefs.layers}
            volume={prefs.volume}
            sustain={sustain}
            onLayers={(layers) => update({ layers })}
            onVolume={(volume) => update({ volume })}
            onSustain={setSustainButton}
            onStop={() => {
              cancelProgram();
              releaseEverything();
              setSustainButton(false);
            }}
          />
        </Card>
      </div>
    </div>
  );
}
