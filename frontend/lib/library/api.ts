import { type ApiResult, api } from "@/lib/api";
import type { ItemKind, LibraryItem, LibraryItemDetail, LibraryList } from "@/lib/library/types";

export const listLibrary = (kind?: ItemKind, q?: string) => {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (q?.trim()) params.set("q", q.trim());
  const query = params.toString();
  return api<LibraryList>(`/api/v1/library${query ? `?${query}` : ""}`);
};

export const saveItem = (body: {
  kind: ItemKind;
  title: string;
  data: Record<string, unknown>;
  file_name?: string;
  file_base64?: string;
}) => api<LibraryItemDetail>("/api/v1/library", { method: "POST", body });

export const getItem = (id: string) => api<LibraryItemDetail>(`/api/v1/library/${id}`);

export const updateItem = (id: string, body: { title?: string; data?: Record<string, unknown> }) =>
  api<LibraryItemDetail>(`/api/v1/library/${id}`, { method: "PATCH", body });

export const deleteItem = (id: string) => api<void>(`/api/v1/library/${id}`, { method: "DELETE" });

export const fileUrl = (id: string) => `/api/v1/library/${id}/file`;

/** The saved .mid file as bytes, for opening a MIDI project again. */
export async function getItemFile(id: string): Promise<ApiResult<ArrayBuffer>> {
  try {
    const res = await fetch(fileUrl(id), { credentials: "same-origin" });
    if (!res.ok) return { ok: false, status: res.status, code: "file_unavailable", message: "The saved file could not be loaded." };
    return { ok: true, data: await res.arrayBuffer() };
  } catch {
    return { ok: false, status: 0, code: "network_error", message: "Could not reach the server. Check your connection and try again." };
  }
}

export type { LibraryItem };
