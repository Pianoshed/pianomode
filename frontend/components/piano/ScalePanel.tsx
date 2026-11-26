"use client";

import { Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type Overlay, overlayFromScale } from "@/lib/piano/highlight";
import { type ScaleInfo, type ScaleResult, generateScale, listScales } from "@/lib/piano/theoryApi";
import { Labelled, RootPicker, prettyNote, selectClass } from "./shared";

type Props = {
  active: boolean;
  onOverlay: (o: Overlay | null) => void;
  onPlaySequence: (notes: number[]) => void;
};

export function ScalePanel({ active, onOverlay, onPlaySequence }: Props) {
  const [scales, setScales] = useState<ScaleInfo[]>([]);
  const [root, setRoot] = useState("C");
  const [scaleId, setScaleId] = useState("major");
  const [result, setResult] = useState<ScaleResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void listScales().then((r) => {
      if (!live) return;
      if (r.ok) setScales(r.data.scales);
      else setError(failureText(r));
    });
    return () => {
      live = false;
    };
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<string, ScaleInfo[]>();
    for (const s of scales) map.set(s.family, [...(map.get(s.family) ?? []), s]);
    return [...map.entries()];
  }, [scales]);

  useEffect(() => {
    if (scales.length === 0) return;
    let live = true;
    void generateScale(root, scaleId).then((r) => {
      if (!live) return;
      if (!r.ok) {
        setError(failureText(r));
        setResult(null);
        onOverlay(null);
        return;
      }
      setError(null);
      setResult(r.data);
      onOverlay(overlayFromScale(r.data));
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root, scaleId, scales.length]);

  const play = () => {
    if (!result) return;
    const up = result.keyboard.map((n) => n.midi).filter((m): m is number => m !== null);
    const first = up[0];
    if (first !== undefined) onPlaySequence([...up, first + 12]);
  };

  return (
    <div hidden={!active} className="space-y-5">
      <RootPicker label="Starting note" value={root} onChange={setRoot} />
      <Labelled label="Scale or mode">
        <select className={selectClass} value={scaleId} onChange={(e) => setScaleId(e.target.value)}>
          {grouped.map(([family, items]) => (
            <optgroup key={family} label={family}>
              {items.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </Labelled>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {result ? (
        <div className="rounded-lg border border-line bg-surface-2 p-4" aria-live="polite">
          <p className="text-xl font-extrabold tracking-tight">
            {prettyNote(result.root)} {result.scale.name.toLowerCase()}
          </p>
          <ol className="mt-3 flex flex-wrap gap-2">
            {result.degrees.map((d) => (
              <li key={d.number} className="rounded-md border border-line bg-surface px-2.5 py-1 text-sm">
                <span className="text-muted">{d.number}</span> <span className="font-semibold">{prettyNote(d.note)}</span>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-sm text-muted">Every key in the scale is marked, in all octaves, with its degree.</p>
          {result.fingering ? (
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid="fingering">
              <dt className="text-muted">Right hand</dt>
              <dd className="font-mono font-semibold">{result.fingering.right_hand.join(" ")}</dd>
              <dt className="text-muted">Left hand</dt>
              <dd className="font-mono font-semibold">{result.fingering.left_hand.join(" ")}</dd>
              <dd className="col-span-2 text-muted">Fingers 1 (thumb) to 5, one octave going up.</dd>
            </dl>
          ) : (
            <p className="mt-3 text-sm text-muted" data-testid="no-fingering">
              No curated fingering for this scale.
            </p>
          )}
          <button type="button" onClick={play} className={`${buttonStyles()} mt-4`}>
            <Play aria-hidden className="h-4 w-4" /> Play scale
          </button>
        </div>
      ) : null}
    </div>
  );
}
