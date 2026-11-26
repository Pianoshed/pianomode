"use client";

import { useRef, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import type { Grid, Hand, Prefer } from "@/lib/midi/api";
import { type Corrections, corrections, exportTracks, parseCorrections } from "@/lib/midi/export";
import type { ParsedMidi } from "@/lib/midi/smf";
import type { TrackEdit, TrackState } from "@/lib/midi/studio";
import { writeMidi } from "@/lib/midi/writer";

type Props = {
  parsed: ParsedMidi;
  fileName: string | null;
  edits: readonly TrackEdit[];
  trackStates: Readonly<Record<number, TrackState>>;
  handEdits: ReadonlyMap<string, Hand>;
  keyChoice: { tonic: string; mode: string } | null;
  grid: Grid;
  prefer: Prefer;
  onRestore: (c: Corrections) => void;
};

function download(name: string, data: BlobPart, type: string): void {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const stem = (name: string | null): string => (name ?? "midi-file").replace(/\.[^.]*$/, "").replace(/[^\w.-]+/g, "-").slice(0, 80) || "midi-file";

/** Keep the work done in MIDI Studio: a MIDI file with the merges, splits, mutes and hand
 *  corrections applied, and a small corrections file that restores the same choices later. The
 *  corrections file holds choices only, never the music, and only fits the file it was saved for. */
export function ExportPanel({ parsed, fileName, edits, trackStates, handEdits, keyChoice, grid, prefer, onRestore }: Props) {
  const [includeMuted, setIncludeMuted] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const pick = useRef<HTMLInputElement | null>(null);

  const exportMidi = () => {
    try {
      const tracks = exportTracks(parsed, edits, trackStates, handEdits, includeMuted);
      if (tracks.length === 0) return setMessage({ tone: "error", text: "Nothing to export: every track is muted or empty." });
      const bytes = writeMidi({ ppq: parsed.ppq, tempoChanges: parsed.tempoChanges, timeSignatures: parsed.timeSignatures, tracks });
      download(`${stem(fileName)}-edited.mid`, bytes as BlobPart, "audio/midi");
      setMessage({ tone: "success", text: `Saved ${tracks.length} ${tracks.length === 1 ? "track" : "tracks"} as a MIDI file.` });
    } catch (e) {
      setMessage({ tone: "error", text: e instanceof Error ? e.message : "The MIDI file could not be written." });
    }
  };

  const saveCorrections = () => {
    const c = corrections({ fileName, parsed, edits, trackStates, handEdits, key: keyChoice, grid, prefer });
    download(`${stem(fileName)}-corrections.json`, JSON.stringify(c, null, 1), "application/json");
    setMessage({ tone: "success", text: "Saved your corrections. Load them again with the same MIDI file." });
  };

  const load = async (file: File | undefined) => {
    if (!file) return;
    const r = parseCorrections(await file.text(), parsed);
    if (!r.ok) return setMessage({ tone: "error", text: r.error });
    onRestore(r.data);
    setMessage({ tone: "success", text: "Corrections restored." });
  };

  return (
    <section aria-label="Save and export" className="space-y-3 rounded-xl border border-line bg-surface p-5">
      <div>
        <h2 className="text-base font-semibold">Save and export</h2>
        <p className="text-sm text-muted">Export the file with your track merges, splits, mutes and hand corrections applied. Or save just your choices and restore them later.</p>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeMuted} onChange={(e) => setIncludeMuted(e.target.checked)} /> Include muted tracks</label>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonStyles({ variant: "primary" })} onClick={exportMidi}>Download edited MIDI</button>
        <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={saveCorrections}>Save corrections</button>
        <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => pick.current?.click()}>Load corrections</button>
        <input ref={pick} type="file" accept="application/json,.json" className="sr-only" tabIndex={-1} aria-label="Corrections file" onChange={(e) => { void load(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
      <p className="text-xs text-muted">Lyrics, controllers and pedal events are not kept in the exported file; it holds notes, tempo and time signature.</p>
      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
    </section>
  );
}
