import { apiBase, apiHeaders } from "@/lib/server-api";
import type { Dashboard, LibraryList } from "@/lib/library/types";

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${apiBase()}${path}`, { headers: await apiHeaders(), cache: "no-store" });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

/** Server-only. Null when the API cannot be reached. */
export const getLibrary = () => get<LibraryList>("/api/v1/library");
export const getDashboard = () => get<Dashboard>("/api/v1/dashboard");
