import type { ItemKind } from "@/lib/library/types";

export const KIND_LABEL: Record<ItemKind, string> = {
  midi: "MIDI project",
  audio: "Audio analysis",
  progression: "Chord progression",
};

/** Where a saved item opens. Progressions need their saved settings, so they are opened by the page. */
export function studioHref(kind: "midi" | "audio", id: string): string {
  return `/${kind}?project=${encodeURIComponent(id)}`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Share of a limit used, 0 to 100. */
export function percentUsed(used: number, max: number): number {
  return max <= 0 ? 0 : Math.min(100, Math.round((used / max) * 100));
}

/** "Today", "Yesterday", "3 days ago", or a date. */
export function relativeDay(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(d)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
