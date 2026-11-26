"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useAction } from "@/components/auth/useAction";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { saveItem, updateItem } from "@/lib/library/api";
import { bytesToBase64 } from "@/lib/library/base64";
import type { ItemKind } from "@/lib/library/types";

export type SavePayload = { data: Record<string, unknown>; fileName?: string; fileBytes?: ArrayBuffer };

/**
 * "Save to My Library" for any tool. A new item asks for a name once; an item that was opened
 * from the library (or has just been saved) offers "Save changes" and "Save as a new copy".
 */
export function SaveToLibrary({
  kind,
  defaultTitle,
  existing,
  build,
  onSaved,
  disabled = false,
}: {
  kind: ItemKind;
  defaultTitle: string;
  existing?: { id: string; title: string } | null;
  build: () => SavePayload;
  onSaved?: (item: { id: string; title: string }) => void;
  disabled?: boolean;
}) {
  const [current, setCurrent] = useState(existing ?? null);
  const [title, setTitle] = useState(existing?.title ?? defaultTitle);
  const [naming, setNaming] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const { pending, error, run } = useAction();

  async function create(name: string) {
    const p = build();
    const r = await run(() =>
      saveItem({
        kind,
        title: name,
        data: p.data,
        ...(p.fileBytes ? { file_name: p.fileName, file_base64: bytesToBase64(p.fileBytes) } : {}),
      }),
    );
    if (!r.ok) return;
    setCurrent({ id: r.data.id, title: r.data.title });
    setTitle(r.data.title);
    setNaming(false);
    setSaved(`Saved as "${r.data.title}".`);
    onSaved?.({ id: r.data.id, title: r.data.title });
  }

  async function saveChanges() {
    if (!current) return;
    const r = await run(() => updateItem(current.id, { data: build().data }));
    if (r.ok) setSaved(`Changes saved to "${r.data.title}".`);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void create(title.trim() || defaultTitle);
  }

  return (
    <div className="space-y-3">
      {error ? <Notice tone="error">{error}</Notice> : null}
      {saved ? (
        <Notice tone="success">
          {saved} <Link href="/library" className="underline underline-offset-4">Open My Library</Link>
        </Notice>
      ) : null}
      {current && !naming ? (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={disabled || pending} onClick={() => void saveChanges()} className={buttonStyles()}>
            {pending ? "Saving…" : "Save changes"}
          </button>
          {kind === "progression" || kind === "audio" || kind === "midi" ? (
            <button type="button" disabled={disabled || pending} onClick={() => { setTitle(`${current.title} (copy)`.slice(0, 120)); setNaming(true); }} className={buttonStyles({ variant: "secondary" })}>
              Save as a new copy
            </button>
          ) : null}
        </div>
      ) : naming || current === null ? (
        naming || !saved ? (
          <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
            <label className="min-w-56 flex-1 text-sm font-medium">
              Name
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={120}
                required
                disabled={disabled}
                className="mt-1 block min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-base text-fg"
              />
            </label>
            <button type="submit" disabled={disabled || pending} className={buttonStyles()}>
              {pending ? "Saving…" : "Save to My Library"}
            </button>
            {naming ? (
              <button type="button" onClick={() => setNaming(false)} className={buttonStyles({ variant: "ghost" })}>
                Cancel
              </button>
            ) : null}
          </form>
        ) : null
      ) : null}
    </div>
  );
}
