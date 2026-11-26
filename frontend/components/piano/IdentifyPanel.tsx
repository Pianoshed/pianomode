"use client";

import { useEffect, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { failureText } from "@/lib/api";
import { type Overlay, overlayFromCandidate } from "@/lib/piano/highlight";
import type { Accidentals } from "@/lib/piano/keys";
import { type ChordIdentify, identifyChord } from "@/lib/piano/theoryApi";
import { prettyNote, useDebounced } from "./shared";

type Props = {
  active: boolean;
  /** The most recent set of keys played together (kept after the keys are released). */
  notes: number[];
  accidentals: Accidentals;
  onOverlay: (o: Overlay | null) => void;
  /** A one-line result for the readout above the keyboard, whichever tab is open. */
  onSummary: (s: HeardSummary | null) => void;
  onClear: () => void;
};

export type HeardSummary = { status: ChordIdentify["status"]; symbol: string | null; others: string[] };

const NOTE_WORDS = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];

export function IdentifyPanel({ active, notes, accidentals, onOverlay, onSummary, onClear }: Props) {
  const settled = useDebounced(notes, 220); // wait for a chord to be fully played
  const [result, setResult] = useState<ChordIdentify | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState(0);

  useEffect(() => {
    if (settled.length === 0) {
      setResult(null);
      setError(null);
      onOverlay(null);
      return;
    }
    let live = true;
    void identifyChord(settled, { prefer: accidentals }).then((r) => {
      if (!live) return;
      if (r.ok) {
        setResult(r.data);
        setError(null);
        setPick(0);
      } else {
        setError(failureText(r));
        setResult(null);
        onOverlay(null);
      }
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, accidentals]);

  useEffect(() => {
    if (!result) {
      onSummary(null);
      return;
    }
    const names = result.candidates.map((c) => c.symbol);
    onSummary({
      status: result.status,
      symbol: result.status === "no_reliable_label" ? null : (names[0] ?? null),
      others: result.status === "no_reliable_label" ? [] : names.slice(1, 3),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  useEffect(() => {
    const c = result?.candidates[pick];
    onOverlay(c && result?.status !== "no_reliable_label" ? overlayFromCandidate(c, settled) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, pick]);

  if (notes.length === 0) {
    return (
      <div hidden={!active}>
        <p className="max-w-[56ch] text-sm text-muted">
          Play a few keys together and the chord they make appears here, with other readings when the notes could be named more than one way.
        </p>
      </div>
    );
  }

  const top = result?.candidates[pick];
  return (
    <div hidden={!active} className="space-y-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          Keys: {notes.map((m) => NOTE_WORDS[m % 12]).join(" ")} <span className="sr-only">({notes.length} notes)</span>
        </p>
        <button type="button" onClick={onClear} className="min-h-11 rounded-lg px-3 text-sm font-semibold text-muted hover:bg-surface-2">
          Clear
        </button>
      </div>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {result?.status === "no_reliable_label" ? (
        <Notice>{result.reason ?? "These notes do not make a chord that can be named reliably."}</Notice>
      ) : null}
      {result && result.status !== "no_reliable_label" && top ? (
        <>
          <div className="rounded-lg border border-line bg-surface-2 p-4">
            {result.status === "ambiguous" ? (
              <p className="mb-1 text-sm font-medium">More than one reading fits these keys.</p>
            ) : null}
            <p className="text-3xl font-extrabold tracking-tight">{prettyNote(top.symbol)}</p>
            <p className="mt-1 text-sm text-muted">
              {top.quality}
              {top.inversion_name && top.inversion ? `, ${top.inversion_name}` : ""}
              {top.rootless ? ", root not played" : ""}
            </p>
            {top.missing_tones.length > 0 ? <p className="mt-2 text-sm">Not played: {top.missing_tones.map(prettyNote).join(", ")}</p> : null}
            {top.extra_tones.length > 0 ? <p className="mt-1 text-sm">Extra notes: {top.extra_tones.map(prettyNote).join(", ")}</p> : null}
            {top.assumptions.length > 0 ? (
              <ul className="mt-2 list-disc pl-5 text-sm text-muted">
                {top.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            ) : null}
          </div>
          {result.candidates.length > 1 ? (
            <div>
              <p className="mb-2 text-sm font-medium">Other readings</p>
              <div className="flex flex-wrap gap-2">
                {result.candidates.map((c, i) => (
                  <button
                    key={c.symbol}
                    type="button"
                    aria-pressed={i === pick}
                    onClick={() => setPick(i)}
                    className={`min-h-11 rounded-lg border px-3 text-sm font-semibold ${i === pick ? "border-accent bg-accent-soft" : "border-line bg-surface hover:bg-surface-2"}`}
                  >
                    {prettyNote(c.symbol)}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <p className="text-xs text-muted">Readings are ranked against each other; the order is a judgement, not a probability. The keys show the reading you pick.</p>
        </>
      ) : null}
    </div>
  );
}
