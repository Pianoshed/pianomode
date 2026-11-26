"use client";

import { Volume2 } from "lucide-react";
import { prettyNote } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import type { Segment } from "@/lib/midi/api";
import { formatTime } from "@/lib/midi/studio";

const STATUS_TEXT: Record<Segment["status"], string> = {
  identified: "One reading fits clearly.",
  ambiguous: "More than one reading fits. Pick one to see it on the keyboard.",
  no_reliable_label: "These notes do not form a chord that can be named reliably.",
  silence: "Nothing sounds here.",
};

export function SegmentDetails({
  segment,
  candidate,
  onCandidate,
  onHear,
  onPlayFrom,
}: {
  segment: Segment;
  candidate: number;
  onCandidate: (i: number) => void;
  onHear: () => void;
  onPlayFrom: () => void;
}) {
  const c = segment.candidates[candidate];
  const n = segment.numeral;
  return (
    <section aria-label="Chord details" className="space-y-4 rounded-xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">
            {c ? prettyNote(c.symbol) : "No reliable label"}
            {segment.status === "ambiguous" ? <span className="ml-2 text-sm font-normal text-muted">uncertain</span> : null}
          </h2>
          <p className="text-sm text-muted">
            {formatTime(segment.start_sec, true)} to {formatTime(segment.end_sec, true)} · beats {segment.start_beat.toFixed(1)} to {segment.end_beat.toFixed(1)}
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={onHear} className={buttonStyles({ variant: "secondary" })}>
            <Volume2 aria-hidden className="h-4 w-4" /> Hear this chord
          </button>
          <button type="button" onClick={onPlayFrom} className={buttonStyles({ variant: "secondary" })}>Play from here</button>
        </div>
      </div>

      <p className="text-sm">{STATUS_TEXT[segment.status]}</p>
      {segment.reason ? <p className="text-sm text-muted">{segment.reason}</p> : null}

      {segment.candidates.length > 1 ? (
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Readings, best first</legend>
          <div className="flex flex-wrap gap-1.5">
            {segment.candidates.map((cand, i) => (
              <button
                key={cand.symbol}
                type="button"
                aria-pressed={candidate === i}
                onClick={() => onCandidate(i)}
                className={`min-h-11 rounded-lg border px-3 text-sm font-semibold ${candidate === i ? "border-accent bg-accent text-accent-fg" : "border-line bg-surface hover:bg-surface-2"}`}
              >
                {prettyNote(cand.symbol)}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-muted">Scores rank the readings against each other. They are not probabilities.</p>
        </fieldset>
      ) : null}

      {c ? (
        <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="font-medium">Bass note</dt><dd>{prettyNote(c.bass)}{c.inversion_name ? ` (${c.inversion_name})` : ""}</dd>
          <dt className="font-medium">Chord tones heard</dt><dd>{c.detected_tones.map(prettyNote).join("  ") || "none"}</dd>
          {c.missing_tones.length ? (<><dt className="font-medium">Not played</dt><dd>{c.missing_tones.map(prettyNote).join("  ")}{c.rootless ? " (a rootless voicing: the root is implied)" : ""}</dd></>) : null}
          {c.extra_tones.length ? (<><dt className="font-medium">Extra notes</dt><dd>{c.extra_tones.map(prettyNote).join("  ")}</dd></>) : null}
          {c.assumptions.length ? (<><dt className="font-medium">Assumes</dt><dd>{c.assumptions.join(" ")}</dd></>) : null}
        </dl>
      ) : null}

      {n ? (
        <div className="rounded-lg border border-line p-3 text-sm">
          <p>
            <span className="font-semibold">{prettyNote(n.figure)}</span>
            {n.function ? <span className="text-muted"> · {n.function}</span> : null}
            {n.borrowed_from ? <span className="text-muted"> · borrowed from {n.borrowed_from}</span> : null}
            {n.applied_to ? <span className="text-muted"> · leads to {n.applied_to}</span> : null}
          </p>
          {n.note ? <p className="mt-1 text-muted">{n.note}</p> : null}
          {n.alternatives.length ? <p className="mt-1 text-muted">Other numerals: {n.alternatives.map(prettyNote).join(", ")}</p> : null}
        </div>
      ) : (
        <p className="text-sm text-muted">No Roman numeral, because no key is available for this chord.</p>
      )}
      {segment.warnings.map((w) => <Notice key={w}>{w}</Notice>)}
    </section>
  );
}
