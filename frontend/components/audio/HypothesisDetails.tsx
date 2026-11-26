"use client";

import { Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { prettyNote } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import type { Hypothesis } from "@/lib/audio/api";
import { PITCH_NAMES } from "@/lib/audio/chords";
import { STATUS_TEXT } from "@/lib/audio/studio";
import { formatTime } from "@/lib/midi/studio";

const field = "min-h-11 rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent";

export function HypothesisDetails({
  h,
  original,
  index,
  count,
  playhead,
  canAddHere,
  busy,
  onHear,
  onPlayFrom,
  onRelabel,
  onEdge,
  onSplit,
  onMerge,
  onDelete,
  onAdd,
}: {
  h: Hypothesis;
  original: Hypothesis | null;
  index: number;
  count: number;
  playhead: number;
  canAddHere: boolean;
  busy: boolean;
  onHear: () => void;
  onPlayFrom: () => void;
  onRelabel: (label: string) => void;
  onEdge: (edge: "start" | "end", to: number) => void;
  onSplit: () => void;
  onMerge: () => void;
  onDelete: () => void;
  onAdd: (label: string) => void;
}) {
  const [label, setLabel] = useState("");
  const [start, setStart] = useState(String(h.start));
  const [end, setEnd] = useState(String(h.end));
  const [addLabel, setAddLabel] = useState("");
  useEffect(() => {
    setStart(h.start.toFixed(2));
    setEnd(h.end.toFixed(2));
    setLabel("");
  }, [h.start, h.end, h.raw_label, index]);

  const title = h.status === "no_chord" ? "No chord" : (h.symbol ?? h.raw_label);
  const evidence = h.pitch_classes?.map((p) => PITCH_NAMES[p]).join("  ");
  return (
    <section aria-label="Chord details" className="space-y-5 rounded-xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">
            {prettyNote(title)}
            {h.origin === "user" ? <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-xs font-normal text-muted">set by you</span> : <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-xs font-normal text-muted">heard, an estimate</span>}
          </h2>
          <p className="text-sm text-muted">{formatTime(h.start, true)} to {formatTime(h.end, true)}</p>
        </div>
        <div className="flex gap-2">
          {h.symbol ? (
            <button type="button" onClick={onHear} className={buttonStyles({ variant: "secondary" })}>
              <Volume2 aria-hidden className="h-4 w-4" /> Hear this chord
            </button>
          ) : null}
          <button type="button" onClick={onPlayFrom} className={buttonStyles({ variant: "secondary" })}>Play from here</button>
        </div>
      </div>

      <p className="text-sm">{STATUS_TEXT[h.status]}</p>
      {original && original.symbol !== h.symbol ? <p className="text-sm text-muted">Originally heard as {original.status === "no_chord" ? "no chord" : prettyNote(original.symbol ?? original.raw_label)}.</p> : null}

      {h.alternatives.length ? (
        <div>
          <h3 className="mb-1.5 text-sm font-medium">Other readings that fit</h3>
          <ul className="flex flex-wrap gap-1.5">
            {h.alternatives.map((a) => (
              <li key={`${a.source}-${a.symbol ?? a.label}`}>
                <button type="button" className="min-h-11 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-surface-2" onClick={() => a.symbol && onRelabel(a.symbol)} disabled={!a.symbol || busy} title="Use this chord for the region">
                  {prettyNote(a.symbol ?? a.label ?? "?")}
                  {a.model_score !== null ? <span className="ml-1.5 text-xs font-normal text-muted">{a.model_score.toFixed(2)}</span> : <span className="ml-1.5 text-xs font-normal text-muted">from the notes heard</span>}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-muted">Numbers are raw similarity scores. They rank the readings against each other and are not probabilities. Choosing one sets the region to that chord (marked as set by you).</p>
        </div>
      ) : null}

      <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">
        {h.model_score !== null ? (<><dt className="font-medium">Raw score</dt><dd>{h.model_score.toFixed(2)} <span className="text-muted">(not a probability)</span></dd></>) : null}
        {h.bass ? (<><dt className="font-medium">Bass note heard</dt><dd>{prettyNote(h.bass)}</dd></>) : null}
        {evidence ? (<><dt className="font-medium">Strongest pitches</dt><dd>{evidence}</dd></>) : null}
        {h.numeral ? (<><dt className="font-medium">Roman numeral</dt><dd>{prettyNote(h.numeral.figure)}{h.numeral.function ? <span className="text-muted"> · {h.numeral.function}</span> : null}{h.numeral.borrowed_from ? <span className="text-muted"> · borrowed from {h.numeral.borrowed_from}</span> : null}</dd></>) : null}
      </dl>
      {h.warnings.map((w) => <Notice key={w}>{w}</Notice>)}

      <fieldset disabled={busy} className="space-y-4 border-t border-line pt-4">
        <legend className="text-sm font-semibold">Correct this region</legend>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (label.trim()) onRelabel(label); }}>
          <label className="block text-sm"><span className="mb-1.5 block font-medium">Change the chord to</span>
            <input className={`${field} w-48`} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="for example Am7 or C/E" maxLength={40} autoComplete="off" spellCheck={false} aria-label="New chord" /></label>
          <button type="submit" className={buttonStyles({ variant: "secondary" })} disabled={!label.trim()}>Change</button>
        </form>
        <div className="flex flex-wrap items-end gap-4">
          {(["start", "end"] as const).map((edge) => (
            <form key={edge} className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); onEdge(edge, Number(edge === "start" ? start : end)); }}>
              <label className="block text-sm"><span className="mb-1.5 block font-medium">{edge === "start" ? "Starts at (s)" : "Ends at (s)"}</span>
                <input className={`${field} w-28`} type="number" step="0.05" min="0" value={edge === "start" ? start : end} onChange={(e) => (edge === "start" ? setStart(e.target.value) : setEnd(e.target.value))} aria-label={edge === "start" ? "Start time in seconds" : "End time in seconds"} /></label>
              <button type="submit" className={buttonStyles({ variant: "secondary" })}>Move</button>
            </form>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onSplit} className={buttonStyles({ variant: "secondary" })}>Split at {formatTime(playhead, true)}</button>
          <button type="button" onClick={onMerge} disabled={index >= count - 1} className={buttonStyles({ variant: "secondary" })}>Join with the next chord</button>
          <button type="button" onClick={onDelete} className={buttonStyles({ variant: "secondary" })}>Remove this chord</button>
        </div>
      </fieldset>
      <fieldset disabled={busy || !canAddHere} className="space-y-2 border-t border-line pt-4">
        <legend className="text-sm font-semibold">Add a chord</legend>
        <p className="text-xs text-muted">{canAddHere ? "The playhead is in an empty stretch, so a chord can go here." : "Remove a chord, or move the playhead into an empty stretch between chords, to add one."}</p>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (addLabel.trim()) { onAdd(addLabel); setAddLabel(""); } }}>
          <input className={`${field} w-48`} value={addLabel} onChange={(e) => setAddLabel(e.target.value)} placeholder="chord, for example G7" maxLength={40} autoComplete="off" spellCheck={false} aria-label="Chord to add" />
          <button type="submit" className={buttonStyles({ variant: "secondary" })} disabled={!addLabel.trim()}>Add</button>
        </form>
      </fieldset>
    </section>
  );
}
