"use client";

import { memo, useEffect, useRef } from "react";
import { type HandNote, type RollView, midiNoteName, noteAtPoint, rollHeight, rollWidth, rollX, rollY, secondsAtX, stepSelection } from "@/lib/midi/studio";

const BLACK = new Set([1, 3, 6, 8, 10]);
const rgb = (name: string, fallback: string): string => {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v ? `rgb(${v})` : fallback;
};

type Props = {
  notes: readonly HandNote[];
  view: RollView;
  selectedKey: string | null;
  onSelect: (note: HandNote | null) => void;
  onSeek: (sec: number) => void;
  onSetHand: (note: HandNote, hand: "L" | "R") => void;
  onAudition: (note: HandNote) => void;
};

/** The notes drawn on a canvas, coloured by hand. The playhead is drawn by the parent as a
 *  separate element so playback does not redraw every note. Everything the canvas shows can also
 *  be done from the keyboard: Left/Right pick the previous/next note, L and R set its hand, and
 *  Enter plays it. */
export const PianoRoll = memo(function PianoRoll({ notes, view, selectedKey, onSelect, onSeek, onSetHand, onAudition }: Props) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const w = rollWidth(view);
  const h = rollHeight(view);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const g = c.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const surface = rgb("--c-surface", "#fff");
    const shade = rgb("--c-surface2", "#eee");
    const line = rgb("--c-border", "#ccc");
    const muted = rgb("--c-muted", "#666");
    const left = rgb("--c-left", "#2b5fd9");
    const right = rgb("--c-right", "#9a5a00");
    const fg = rgb("--c-fg", "#111");
    g.fillStyle = surface;
    g.fillRect(0, 0, w, h);
    g.font = "10px system-ui, sans-serif";
    g.textBaseline = "middle";
    for (let m = view.lo; m <= view.hi; m++) {
      const y = rollY(view, m);
      if (BLACK.has(m % 12)) {
        g.fillStyle = shade;
        g.fillRect(view.left, y, w - view.left, view.rowH);
      }
      if (m % 12 === 0) {
        g.fillStyle = line;
        g.fillRect(view.left, y + view.rowH - 1, w - view.left, 1);
        g.fillStyle = muted;
        g.fillText(midiNoteName(m), 2, y + view.rowH / 2);
      }
    }
    // second marks
    g.fillStyle = line;
    const step = view.pxPerSec >= 30 ? 1 : view.pxPerSec >= 12 ? 5 : 15;
    for (let s = 0; s <= view.duration; s += step) g.fillRect(rollX(view, s), 0, 1, h);
    for (const n of notes) {
      const x = rollX(view, n.start_sec);
      const width = Math.max(3, (n.end_sec - n.start_sec) * view.pxPerSec - 1);
      const y = rollY(view, n.midi);
      g.fillStyle = n.hand === "L" ? left : n.hand === "R" ? right : muted;
      g.globalAlpha = n.handSource === "auto" ? 0.62 : 1; // suggestions are lighter than decisions
      g.fillRect(x, y + 1, width, view.rowH - 2);
      g.globalAlpha = 1;
      if (n.key === selectedKey) {
        g.strokeStyle = fg;
        g.lineWidth = 2;
        g.strokeRect(x - 1, y, width + 2, view.rowH);
      }
    }
  }, [notes, view, selectedKey, w, h]);

  const pointer = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const hit = noteAtPoint(notes, view, x, y);
    onSelect(hit);
    if (!hit && x >= view.left) onSeek(secondsAtX(view, x));
  };

  const selected = notes.find((n) => n.key === selectedKey) ?? null;
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const next = stepSelection(notes, selected, e.key === "ArrowRight" ? 1 : -1);
      if (next) {
        onSelect(next);
        onAudition(next);
      }
    } else if ((e.key === "l" || e.key === "L" || e.key === "r" || e.key === "R") && selected) {
      e.preventDefault();
      onSetHand(selected, e.key.toLowerCase() === "l" ? "L" : "R");
    } else if (e.key === "Enter" && selected) {
      e.preventDefault();
      onAudition(selected);
    }
  };

  return (
    <div
      tabIndex={0}
      role="application"
      aria-label="Piano roll. Left and right arrows choose the previous or next note, L or R sets the hand for the chosen note, Enter plays it."
      onKeyDown={key}
      className="rounded-lg"
    >
      <canvas ref={canvas} onClick={pointer} style={{ width: w, height: h, display: "block", cursor: "pointer" }} data-testid="piano-roll" data-view={JSON.stringify({ lo: view.lo, hi: view.hi, left: view.left, top: view.top, rowH: view.rowH, pxPerSec: view.pxPerSec })} />
      <p className="sr-only" aria-live="polite">
        {selected ? `${selected.name}, ${selected.hand === "L" ? "left" : selected.hand === "R" ? "right" : "no"} hand${selected.handSource === "auto" ? " (suggested)" : ""}, from ${selected.start_sec.toFixed(1)} seconds` : ""}
      </p>
    </div>
  );
});
