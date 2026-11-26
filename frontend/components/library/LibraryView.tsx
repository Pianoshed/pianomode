"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAction } from "@/components/auth/useAction";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { deleteItem, fileUrl, getItem, listLibrary, updateItem } from "@/lib/library/api";
import { KIND_LABEL, formatBytes, percentUsed, relativeDay, studioHref } from "@/lib/library/format";
import { progressionHref, restoreProgression } from "@/lib/library/progression";
import type { ItemKind, LibraryItem, LibraryList } from "@/lib/library/types";

const TABS: { value: ItemKind | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "midi", label: "MIDI projects" },
  { value: "audio", label: "Audio analyses" },
  { value: "progression", label: "Progressions" },
];

export function LibraryView({ initial, canOpen }: { initial: LibraryList; canOpen: boolean }) {
  const router = useRouter();
  const [data, setData] = useState(initial);
  const [tab, setTab] = useState<ItemKind | "all">("all");
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const { pending, error, run } = useAction();
  const [query, setQuery] = useState("");
  const firstRun = useRef(true);

  // Search as the person types (after a short pause), asking the server so the usage line stays true.
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    const t = setTimeout(async () => {
      const r = await listLibrary(undefined, query);
      if (r.ok) setData(r.data);
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const shown = data.items.filter((i) => tab === "all" || i.kind === tab);
  const u = data.usage;

  async function refresh() {
    const r = await listLibrary(undefined, query);
    if (r.ok) setData(r.data);
  }

  async function open(item: LibraryItem) {
    if (item.kind !== "progression") return; // MIDI and audio open through their own page link
    const r = await run(() => getItem(item.id));
    if (!r.ok) return;
    const settings = restoreProgression(r.data.data);
    if (!settings) return;
    router.push(progressionHref(settings));
  }

  async function remove(item: LibraryItem) {
    if (!window.confirm(`Delete "${item.title}" from My Library? This cannot be undone.`)) return;
    const r = await run(() => deleteItem(item.id));
    if (r.ok) await refresh();
  }

  async function rename() {
    if (!renaming) return;
    const r = await run(() => updateItem(renaming.id, { title: renaming.title }));
    if (r.ok) {
      setRenaming(null);
      await refresh();
    }
  }

  return (
    <div className="grid max-w-4xl gap-4">
      {!canOpen ? (
        <Notice>
          Your plan has ended, so you can look at, download and delete your saved work, but opening it in the studios
          needs a plan. <Link href="/subscription" className="underline underline-offset-4">Subscription</Link>
        </Notice>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}

      <Card title="Saved work">
        <label className="mb-4 block text-sm font-medium">
          Search by name
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="mt-1 block min-h-11 w-full max-w-md rounded-lg border border-line bg-surface px-3 text-base text-fg"
          />
        </label>
        <div role="tablist" aria-label="Kind" className="mb-4 flex flex-wrap gap-2">
          {TABS.map((t) => (
            <button
              key={t.value}
              role="tab"
              aria-selected={tab === t.value}
              type="button"
              onClick={() => setTab(t.value)}
              className={buttonStyles({ variant: tab === t.value ? "primary" : "secondary" })}
            >
              {t.label}
            </button>
          ))}
        </div>

        {shown.length === 0 ? (
          <EmptyState>
            {data.items.length === 0 && query.trim() ? (
              "Nothing matches that name."
            ) : data.items.length === 0 ? (
              <>
                Nothing saved yet. Use <strong>Save to My Library</strong> in{" "}
                <Link href="/midi" className="underline underline-offset-4">MIDI Studio</Link>, the{" "}
                <Link href="/audio" className="underline underline-offset-4">Audio Analyzer</Link> or on a{" "}
                <Link href="/progressions" className="underline underline-offset-4">chord progression</Link>.
              </>
            ) : (
              "Nothing of this kind is saved."
            )}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {shown.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0 flex-1">
                  {renaming?.id === item.id ? (
                    <form onSubmit={(e) => { e.preventDefault(); void rename(); }} className="flex flex-wrap items-center gap-2">
                      <input
                        aria-label="New name"
                        autoFocus
                        value={renaming.title}
                        onChange={(e) => setRenaming({ id: item.id, title: e.target.value })}
                        maxLength={120}
                        className="min-h-11 min-w-48 flex-1 rounded-lg border border-line bg-surface px-3 text-base text-fg"
                      />
                      <button type="submit" disabled={pending || !renaming.title.trim()} className={buttonStyles()}>Save</button>
                      <button type="button" onClick={() => setRenaming(null)} className={buttonStyles({ variant: "ghost" })}>Cancel</button>
                    </form>
                  ) : (
                    <>
                      <p className="truncate font-semibold">{item.title}</p>
                      <p className="text-sm text-muted">
                        {KIND_LABEL[item.kind]}
                        {item.file_name ? ` · ${item.file_name} (${formatBytes(item.file_size)})` : ""} · Saved {relativeDay(item.updated_at)}
                      </p>
                    </>
                  )}
                </div>
                {renaming?.id === item.id ? null : (
                  <div className="flex flex-wrap gap-2">
                    {canOpen ? (
                      item.kind === "progression" ? (
                        <button type="button" disabled={pending} onClick={() => void open(item)} className={buttonStyles()}>Open</button>
                      ) : (
                        <Link href={studioHref(item.kind, item.id)} className={buttonStyles()}>Open</Link>
                      )
                    ) : null}
                    {item.kind === "midi" ? (
                      <a href={fileUrl(item.id)} download={item.file_name ?? "project.mid"} className={buttonStyles({ variant: "secondary" })}>Download</a>
                    ) : null}
                    {canOpen ? (
                      <button type="button" onClick={() => setRenaming({ id: item.id, title: item.title })} className={buttonStyles({ variant: "ghost" })}>Rename</button>
                    ) : null}
                    <button type="button" disabled={pending} onClick={() => void remove(item)} className={buttonStyles({ variant: "ghost" })}>Delete</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <p className="text-sm text-muted" aria-label="Space used">
        {u.items} of {u.max_items} items · {formatBytes(u.bytes)} of {formatBytes(u.max_bytes)} used ({percentUsed(u.bytes, u.max_bytes)}%).
        Audio analyses keep only your settings and corrections, not the recording, so you open the same file again to hear it.
      </p>
    </div>
  );
}
