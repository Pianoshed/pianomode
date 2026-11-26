"use client";

import { Volume2, VolumeX } from "lucide-react";
import { buttonStyles } from "@/components/ui/button";
import { type Layer, MAX_LAYERS, SOUND_IDS, SOUND_INFO, type SoundId } from "@/lib/piano/sounds";

type Props = {
  layers: Layer[];
  volume: number;
  sustain: boolean;
  onLayers: (l: Layer[]) => void;
  onVolume: (v: number) => void;
  onSustain: (on: boolean) => void;
  onStop: () => void;
};

export function SoundPanel({ layers, volume, sustain, onLayers, onVolume, onSustain, onStop }: Props) {
  const gainOf = (id: SoundId) => layers.find((l) => l.sound === id)?.gain;

  const toggle = (id: SoundId, on: boolean) => {
    if (on) {
      if (layers.length >= MAX_LAYERS) return;
      onLayers([...layers, { sound: id, gain: 1 }]);
    } else if (layers.length > 1) {
      onLayers(layers.filter((l) => l.sound !== id)); // at least one sound always stays on
    }
  };

  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="text-sm font-medium">Sounds</legend>
        <p className="mb-2 mt-0.5 text-xs text-muted">Choose up to {MAX_LAYERS} and they play together. These are synthesised sounds, not recordings.</p>
        <ul className="space-y-1">
          {SOUND_IDS.map((id) => {
            const gain = gainOf(id);
            const on = gain !== undefined;
            const blocked = !on && layers.length >= MAX_LAYERS;
            return (
              <li key={id} className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg px-1 py-0.5">
                <label className={`flex min-h-11 min-w-[11rem] cursor-pointer items-center gap-2.5 text-sm ${blocked ? "opacity-50" : ""}`}>
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={blocked || (on && layers.length === 1)}
                    onChange={(e) => toggle(id, e.target.checked)}
                    className="h-4 w-4 accent-[rgb(var(--c-accent))]"
                  />
                  <span>
                    <span className="font-semibold">{SOUND_INFO[id].label}</span>
                    <span className="block text-xs text-muted">{SOUND_INFO[id].description}</span>
                  </span>
                </label>
                {on ? (
                  <label className="flex min-w-[10rem] flex-1 items-center gap-2 text-xs text-muted">
                    Level
                    <input
                      type="range"
                      min={0.1}
                      max={1}
                      step={0.05}
                      value={gain}
                      aria-label={`${SOUND_INFO[id].label} level`}
                      onChange={(e) => onLayers(layers.map((l) => (l.sound === id ? { ...l, gain: Number(e.target.value) } : l)))}
                      className="min-h-11 flex-1 accent-[rgb(var(--c-accent))]"
                    />
                  </label>
                ) : null}
              </li>
            );
          })}
        </ul>
      </fieldset>

      <label className="flex items-center gap-3 text-sm">
        <Volume2 aria-hidden className="h-4 w-4 shrink-0 text-muted" />
        <span className="font-medium">Volume</span>
        <input type="range" min={0} max={1} step={0.01} value={volume} onChange={(e) => onVolume(Number(e.target.value))} className="min-h-11 flex-1 accent-[rgb(var(--c-accent))]" />
      </label>

      <div className="flex flex-wrap gap-2">
        <button type="button" aria-pressed={sustain} onClick={() => onSustain(!sustain)} className={buttonStyles({ variant: sustain ? "primary" : "secondary" })}>
          Sustain {sustain ? "on" : "off"}
        </button>
        <button type="button" onClick={onStop} className={buttonStyles({ variant: "secondary" })}>
          <VolumeX aria-hidden className="h-4 w-4" /> Stop all sound
        </button>
      </div>
      <p className="text-xs text-muted">Hold Space for the sustain pedal while playing.</p>
    </div>
  );
}
