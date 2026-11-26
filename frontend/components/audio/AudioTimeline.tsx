"use client";

import { memo } from "react";
import { prettyNote } from "@/components/piano/shared";
import type { Hypothesis } from "@/lib/audio/api";
import { look } from "@/lib/audio/studio";
import { formatTime } from "@/lib/midi/studio";

/** One cell per region, as wide as it lasts. Styling carries the kind of claim: a solid border for
 *  a clear estimate, dashed for an ambiguous one, dotted for no chord, and the accent colour for
 *  a chord the person set. Text always says it too (a question mark, "no chord"). */
export const AudioTimeline = memo(function AudioTimeline({
  hypotheses,
  selected,
  current,
  width,
  duration,
  onSelect,
}: {
  hypotheses: readonly Hypothesis[];
  selected: number | null;
  current: number | null;
  width: number;
  duration: number;
  onSelect: (i: number) => void;
}) {
  return (
    <ol className="relative flex" style={{ width, height: 64 }} aria-label="Chords in time order">
      {hypotheses.map((h, i) => {
        const l = look(h);
        const w = Math.max(2, ((h.end - h.start) / duration) * width);
        return (
          <li key={`${h.start}-${i}`} style={{ width: w, flex: "none" }} className="px-px">
            <button
              type="button"
              onClick={() => onSelect(i)}
              aria-pressed={selected === i}
              aria-current={current === i ? "true" : undefined}
              aria-label={`${formatTime(h.start, true)}: ${l.label}${l.sublabel ? `, numeral ${l.sublabel}` : ""}, ${l.kind === "ambiguous" ? "ambiguous estimate" : l.kind === "user" ? "set by you" : l.kind === "none" ? "no chord" : l.kind === "unknown" ? "not understood" : "estimate"}`}
              title={`${l.label} (${formatTime(h.start, true)} to ${formatTime(h.end, true)})`}
              className={`flex h-full w-full min-w-0 flex-col items-center justify-center overflow-hidden rounded-md border px-0.5 text-center transition-colors ${
                selected === i
                  ? "border-accent bg-accent-soft"
                  : current === i
                    ? "border-accent bg-surface-2"
                    : l.kind === "user"
                      ? "border-hand-right bg-surface hover:bg-surface-2"
                      : l.kind === "ambiguous"
                        ? "border-dashed border-muted bg-surface hover:bg-surface-2"
                        : l.kind === "none"
                          ? "border-dotted border-muted bg-surface-2 text-muted hover:bg-surface"
                          : l.kind === "unknown"
                            ? "border-dotted border-muted bg-surface-2 hover:bg-surface"
                            : "border-line bg-surface hover:bg-surface-2"
              }`}
            >
              <span className="max-w-full truncate text-sm font-bold leading-tight">{w > 28 ? prettyNote(l.label) : ""}</span>
              {l.sublabel && w > 36 ? <span className="text-xs text-muted">{l.sublabel}</span> : null}
            </button>
          </li>
        );
      })}
    </ol>
  );
});
