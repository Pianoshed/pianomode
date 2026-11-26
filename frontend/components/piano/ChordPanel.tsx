"use client";

import { Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type Overlay, overlayFromChord, overlayFromVoicing } from "@/lib/piano/highlight";
import {
  type ChordConstruct,
  type ChordRequest,
  type ChordTypeInfo,
  constructChord,
  generateVoicings,
  listChordTypes,
} from "@/lib/piano/theoryApi";
import { Check, Labelled, RootPicker, prettyNote, selectClass } from "./shared";

type Skill = "beginner" | "intermediate" | "advanced" | "expert";

type Props = {
  active: boolean;
  onOverlay: (o: Overlay | null) => void;
  onPlay: (notes: number[]) => void;
};

export function ChordPanel({ active, onOverlay, onPlay }: Props) {
  const [types, setTypes] = useState<ChordTypeInfo[]>([]);
  const [typesError, setTypesError] = useState<string | null>(null);
  const [root, setRoot] = useState("C");
  const [typeId, setTypeId] = useState("major");
  const [inversion, setInversion] = useState(0);
  const [octave, setOctave] = useState(4);
  const [everywhere, setEverywhere] = useState(false);
  const [twoHands, setTwoHands] = useState(false);
  const [skill, setSkill] = useState<Skill>("intermediate");
  const [typed, setTyped] = useState("");
  const [symbol, setSymbol] = useState<string | null>(null); // a typed symbol overrides the pickers
  const [result, setResult] = useState<ChordConstruct | null>(null);
  const [playKeys, setPlayKeys] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [voicingNote, setVoicingNote] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void listChordTypes().then((r) => {
      if (!live) return;
      if (r.ok) setTypes(r.data.types);
      else setTypesError(failureText(r));
    });
    return () => {
      live = false;
    };
  }, []);

  const typeInfo = types.find((t) => t.id === typeId);
  const maxInversion = Math.max(0, (typeInfo?.formula.length ?? 3) - 1);
  const grouped = useMemo(() => {
    const map = new Map<string, ChordTypeInfo[]>();
    for (const t of types) map.set(t.family, [...(map.get(t.family) ?? []), t]);
    return [...map.entries()];
  }, [types]);

  const request: ChordRequest | null = useMemo(() => {
    if (symbol) return { symbol, octave };
    if (types.length === 0) return null;
    return { root, type: typeId, octave, inversion: Math.min(inversion, maxInversion) };
  }, [symbol, root, typeId, octave, inversion, maxInversion, types.length]);

  useEffect(() => {
    if (!request) return;
    let live = true;
    void (async () => {
      const r = await constructChord(request);
      if (!live) return;
      if (!r.ok) {
        setError(failureText(r));
        setResult(null);
        setPlayKeys([]);
        onOverlay(null);
        return;
      }
      setError(null);
      setResult(r.data);
      setVoicingNote(null);
      if (twoHands && !everywhere) {
        const v = await generateVoicings(r.data.chord.symbol, skill);
        if (!live) return;
        if (v.ok) {
          const o = overlayFromVoicing(r.data, v.data);
          if (o) {
            const first = v.data.voicings[0]?.voicing;
            setPlayKeys([...(first?.left ?? []), ...(first?.right ?? [])].sort((a, b) => a - b));
            onOverlay(o);
            return;
          }
          setVoicingNote(v.data.message ?? "No two-hand voicing was found for this chord, so the single-hand notes are shown.");
        } else setVoicingNote(failureText(v));
      }
      setPlayKeys(r.data.midi_notes);
      onOverlay(overlayFromChord(r.data, everywhere));
    })();
    return () => {
      live = false;
    };
    // onOverlay is stable (a state setter wrapper); listing it would re-run on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request, everywhere, twoHands, skill]);

  const applyTyped = () => {
    const text = typed.trim();
    if (text) setSymbol(text);
  };

  return (
    <div hidden={!active} className="space-y-5">
      {typesError ? <Notice tone="error">{typesError}</Notice> : null}
      <RootPicker label="Root" value={symbol ? "" : root} onChange={(v) => { setSymbol(null); setRoot(v); }} />
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="sm:col-span-3">
          <Labelled label="Chord type">
            <select className={selectClass} value={symbol ? "" : typeId} onChange={(e) => { setSymbol(null); setTypeId(e.target.value); setInversion(0); }}>
              {symbol ? <option value="">Typed symbol</option> : null}
              {grouped.map(([family, items]) => (
                <optgroup key={family} label={family}>
                  {items.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}{t.symbol ? ` (${t.symbol})` : ""}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </Labelled>
        </div>
        <Labelled label="Inversion">
          <select className={selectClass} value={Math.min(inversion, maxInversion)} disabled={symbol !== null} onChange={(e) => setInversion(Number(e.target.value))}>
            {Array.from({ length: maxInversion + 1 }, (_, i) => (
              <option key={i} value={i}>
                {["Root position", "First inversion", "Second inversion", "Third inversion", "Fourth inversion", "Fifth inversion", "Sixth inversion"][i]}
              </option>
            ))}
          </select>
        </Labelled>
        <Labelled label="Octave">
          <select className={selectClass} value={octave} onChange={(e) => setOctave(Number(e.target.value))}>
            {[2, 3, 4, 5].map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </Labelled>
      </div>

      <div className="flex gap-2">
        <label className="min-w-0 flex-1 text-sm">
          <span className="mb-1.5 block font-medium">Or type a chord symbol</span>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") applyTyped(); }}
            placeholder="Dm7/C"
            autoCapitalize="off"
            autoComplete="off"
            spellCheck={false}
            className={selectClass}
          />
        </label>
        <button type="button" onClick={applyTyped} className={`${buttonStyles({ variant: "secondary" })} self-end`}>
          Show
        </button>
      </div>

      <div className="grid gap-x-6 sm:grid-cols-2">
        <Check checked={everywhere} onChange={setEverywhere}>
          Show the chord tones in every octave
        </Check>
        <Check checked={twoHands} onChange={setTwoHands}>
          Show a two-hand voicing
        </Check>
      </div>
      {twoHands && !everywhere ? (
        <Labelled label="Voicing level" hint="Left hand is blue and right hand is amber on the keys.">
          <select className={selectClass} value={skill} onChange={(e) => setSkill(e.target.value as Skill)}>
            <option value="beginner">Beginner: simple shapes</option>
            <option value="intermediate">Intermediate</option>
            <option value="advanced">Advanced: richer voicings</option>
            <option value="expert">Expert</option>
          </select>
        </Labelled>
      ) : null}

      {error ? <Notice tone="error">{error}</Notice> : null}
      {voicingNote ? <Notice>{voicingNote}</Notice> : null}

      {result ? (
        <div className="rounded-lg border border-line bg-surface-2 p-4" aria-live="polite">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-2xl font-extrabold tracking-tight">{prettyNote(result.chord.symbol)}</p>
            <p className="text-sm text-muted">
              {result.chord.quality}
              {result.chord.inversion_name && result.chord.inversion ? `, ${result.chord.inversion_name}` : ""}
            </p>
          </div>
          <ul className="mt-3 flex flex-wrap gap-2">
            {result.chord.tones.map((t) => (
              <li key={t.name + t.interval} className="rounded-md border border-line bg-surface px-2.5 py-1 text-sm">
                <span className="font-semibold">{prettyNote(t.name)}</span> <span className="text-muted">{t.interval}</span>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => onPlay(playKeys)} disabled={playKeys.length === 0} className={`${buttonStyles()} mt-4`}>
            <Play aria-hidden className="h-4 w-4" /> Play chord
          </button>
        </div>
      ) : null}
    </div>
  );
}
