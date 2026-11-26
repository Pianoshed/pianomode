"use client";

import { Pause, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PianoKeyboard } from "@/components/piano/PianoKeyboard";
import { prettyNote } from "@/components/piano/shared";
import { buttonStyles } from "@/components/ui/button";
import type { Example } from "@/lib/lessons/api";
import { centreOfItem, eventsFor, exampleBeats, itemAtBeat, overlayForItem } from "@/lib/lessons/lesson";
import { PianoAudio, type Playback } from "@/lib/piano/audio";
import { keyFor } from "@/lib/piano/keys";
import { DEFAULT_PREFS, type Prefs, loadPrefs } from "@/lib/piano/prefs";

/** One lesson example: the keyboard shows the selected item, items can be clicked and heard one
 *  by one, and Play runs the whole example while the keyboard follows along. Everything shown
 *  (notes, numerals, timing) was built by the theory engine. */
export function ExamplePlayer({ example }: { example: Example }) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<PianoAudio | null>(null);
  const run = useRef<{ pb: Playback; startedAt: number; raf: number } | null>(null);
  const audio = useCallback(() => (audioRef.current ??= new PianoAudio()), []);

  useEffect(() => setPrefs(loadPrefs(window.localStorage)), []);

  const stop = useCallback(() => {
    const r = run.current;
    if (r) {
      cancelAnimationFrame(r.raf);
      r.pb.stop();
      run.current = null;
    }
    audioRef.current?.allNotesOff();
    setPlaying(false);
  }, []);
  useEffect(() => stop, [stop]);

  const item = example.items[Math.min(index, example.items.length - 1)];
  const overlay = useMemo(() => overlayForItem(example, index), [example, index]);

  useEffect(() => {
    const el = scrollRef.current;
    const mid = item ? centreOfItem(item) : null;
    const k = mid === null ? undefined : keyFor(mid);
    if (el && k) el.scrollLeft = Math.max(0, (k.x + 0.5) * prefs.keyWidth - el.clientWidth / 2);
  }, [item, prefs.keyWidth]);

  const playAll = async () => {
    if (playing) return stop();
    const a = audio();
    if (!(await a.resume())) {
      setProblem("This browser could not start sound. The notes are still shown on the keyboard.");
      return;
    }
    setProblem(null);
    a.allNotesOff();
    const pb = a.schedule(eventsFor(example), example.tempo, prefs.layers);
    const secondsPerBeat = 60 / example.tempo;
    const end = exampleBeats(example) * secondsPerBeat + 0.3;
    const startedAt = performance.now();
    const tick = () => {
      const elapsed = (performance.now() - startedAt) / 1000;
      if (elapsed >= end) return stop();
      setIndex(itemAtBeat(example, elapsed / secondsPerBeat));
      if (run.current) run.current.raf = requestAnimationFrame(tick);
    };
    run.current = { pb, startedAt, raf: 0 };
    setIndex(itemAtBeat(example, 0));
    setPlaying(true);
    run.current.raf = requestAnimationFrame(tick);
  };

  const hearItem = async (i: number) => {
    stop();
    setIndex(i);
    const it = example.items[i];
    if (!it || !(await audio().resume())) return;
    audio().schedule([{ notes: it.midi, start: 0, duration: example.type === "scale" ? 1 : 2.5 }], 100, prefs.layers);
  };

  return (
    <figure className="my-4 rounded-xl border border-line bg-surface p-3" aria-label={example.caption}>
      <PianoKeyboard
        keyWidth={prefs.keyWidth}
        held={new Set()}
        overlay={overlay}
        labels={{ mode: "none", accidentals: prefs.accidentals, middleC: prefs.middleC, unicode: prefs.unicode }}
        scrollRef={scrollRef}
        onKeyDown={(n, v) => void audio().resume().then(() => audio().noteOn(n, v, prefs.layers))}
        onKeyUp={(n) => audio().noteOff(n)}
      />
      <figcaption className="mt-3 text-sm">{prettyNote(example.caption)}</figcaption>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => void playAll()} className={buttonStyles({ variant: "primary" })}>
          {playing ? <Pause aria-hidden className="h-4 w-4" /> : <Play aria-hidden className="h-4 w-4" />}
          {playing ? "Stop" : "Play"}
        </button>
        {example.items.length > 1 ? (
          <ol className="flex flex-wrap gap-1.5" aria-label="Parts of this example">
            {example.items.map((it, i) => (
              <li key={`${it.label}-${i}`}>
                <button
                  type="button"
                  aria-current={i === index ? "true" : undefined}
                  onClick={() => void hearItem(i)}
                  className={`min-h-11 rounded-lg border px-3 text-sm ${i === index ? "border-accent bg-accent-soft font-semibold" : "border-line hover:bg-surface-2"}`}
                >
                  {prettyNote(it.label)}
                  {it.detail && example.type !== "interval" ? <span className="ml-1.5 text-xs text-muted">{it.detail}</span> : null}
                </button>
              </li>
            ))}
          </ol>
        ) : item ? (
          <p className="text-sm text-muted">{item.notes.map(prettyNote).join("  ")}</p>
        ) : null}
      </div>
      {problem ? <p className="mt-2 text-sm text-danger" role="alert">{problem}</p> : null}
    </figure>
  );
}
