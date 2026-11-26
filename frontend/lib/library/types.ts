export type ItemKind = "midi" | "audio" | "progression";

export type LibraryItem = {
  id: string;
  kind: ItemKind;
  title: string;
  file_name: string | null;
  file_size: number;
  created_at: string;
  updated_at: string;
  last_opened_at: string | null;
};
export type LibraryItemDetail = LibraryItem & { data: Record<string, unknown> };
export type LibraryList = {
  items: LibraryItem[];
  usage: { items: number; max_items: number; bytes: number; max_bytes: number };
};

export type Dashboard = {
  continue_learning: { id: string; title: string; goals_met: number; goals_total: number; progress_percent: number }[];
  recommended: { id: string; title: string; summary: string; reason: string } | null;
  recent_projects: { id: string; kind: "midi" | "audio"; title: string; opened_at: string }[];
  saved_progressions: { id: string; title: string; data: Record<string, unknown> }[];
  activity: { date: string; count: number }[];
  activity_total: number;
};
