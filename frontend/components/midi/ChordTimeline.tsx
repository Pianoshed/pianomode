"use client";

import { memo } from "react";
import { prettyNote } from "@/components/piano/shared";
import type { Segment } from "@/lib/midi/api";
import { formatTime, segmentLook } from "@/lib/midi/studio";

/** One cell per analysed region, as wide as it lasts. An uncertain reading is marked with a
 *  question mark and a dashed border, and a region with no reliable label shows "?", so the
 *  timeline never states more than the analysis does. */
export const ChordTimeline = memo(function ChordTimeline({
  segments,
  selected,
  current,
  pxPerSec,
  onSelect,
}: {
  segments: readonly Segment[];
  selected: number | null;
  current: number | null;
  pxPerSec: number;
  onSelect: (i: number) => void;
}) {
  return (
    <ol className="flex gap-0.5 overflow-visible" aria-label="Chords in time order" style={{ paddingLeft: 28 }}>
      {segments.map((s, i) => {
        const look = segmentLook(s);
        const width = Math.max(44, (s.end_sec - s.start_sec) * pxPerSec - 2);
        const state = [look.kind === "ambiguous" ? "ambiguous" : look.kind === "unknown" ? "no reliable label" : look.kind === "silence" ? "silence" : "identified"];
        return (
          <li key={`${s.start_beat}-${i}`} style={{ width, flex: "none" }}>
            <button
              type="button"
              onClick={() => onSelect(i)}
              aria-pressed={selected === i}
              aria-current={current === i ? "true" : undefined}
              aria-label={`${formatTime(s.start_sec, true)}: ${look.label || "silence"}${look.sublabel ? `, numeral ${look.sublabel}` : ""}, ${state[0]}`}
              disabled={look.kind === "silence"}
              className={`flex min-h-14 w-full flex-col items-center justify-center rounded-md border px-1 text-center transition-colors ${
                look.kind === "silence"
                  ? "border-transparent opacity-40"
                  : selected === i
                    ? "border-accent bg-accent-soft"
                    : current === i
                      ? "border-accent bg-surface-2"
                      : look.kind === "identified"
                        ? "border-line bg-surface hover:bg-surface-2"
                        : look.kind === "ambiguous"
                          ? "border-dashed border-muted bg-surface hover:bg-surface-2"
                          : "border-dotted border-muted bg-surface-2 text-muted hover:bg-surface"
              }`}
            >
              <span className="text-sm font-bold leading-tight">{prettyNote(look.label)}</span>
              {look.sublabel ? <span className="text-xs text-muted">{look.sublabel}</span> : null}
            </button>
          </li>
        );
      })}
    </ol>
  );
});
