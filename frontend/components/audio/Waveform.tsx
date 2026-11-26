"use client";

import { memo, useEffect, useRef } from "react";
import type { Hypothesis } from "@/lib/audio/api";
import { waveformPeaks } from "@/lib/audio/studio";

const rgb = (name: string, fallback: string): string => {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v ? `rgb(${v})` : fallback;
};

/** The recording's loudness over time with the chord boundaries marked. Clicking it moves the
 *  playhead; the playhead itself is drawn by the parent so playing does not redraw the waveform.
 *  The same position can be set from the keyboard with the slider the parent provides. */
export const Waveform = memo(function Waveform({
  samples,
  duration,
  regions,
  width,
  onSeek,
}: {
  samples: Float32Array;
  duration: number;
  regions: readonly Pick<Hypothesis, "start" | "end" | "origin">[];
  width: number;
  onSeek: (sec: number) => void;
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const height = 72;
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = Math.round(width * dpr);
    c.height = Math.round(height * dpr);
    const g = c.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = rgb("--c-surface2", "#eee");
    g.fillRect(0, 0, width, height);
    const peaks = waveformPeaks(samples, Math.max(1, Math.floor(width)));
    const top = Math.max(0.05, Math.max(...peaks));
    g.fillStyle = rgb("--c-muted", "#777");
    peaks.forEach((p, x) => {
      const h = Math.max(1, (p / top) * (height - 8));
      g.fillRect(x, (height - h) / 2, 1, h);
    });
    const accent = rgb("--c-accent", "#2a7");
    const user = rgb("--c-right", "#a60");
    for (const r of regions) {
      const x = (r.start / duration) * width;
      g.fillStyle = r.origin === "user" ? user : accent;
      g.fillRect(x, 0, 1, height);
    }
  }, [samples, duration, regions, width]);
  return (
    <canvas
      ref={ref}
      aria-hidden
      data-testid="waveform"
      style={{ width, height, display: "block", cursor: "pointer" }}
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onSeek(Math.min(duration, Math.max(0, ((e.clientX - r.left) / r.width) * duration)));
      }}
    />
  );
});
