import { cookies } from "next/headers";
import { apiBase, apiHeaders } from "@/lib/server-api";
import type { User } from "@/lib/roles";

export type { Role, User } from "@/lib/roles";
export { hasAnyRole } from "@/lib/roles";

type MeResponse = {
  id: string;
  display_name: string;
  roles: User["roles"];
  institution_role?: "owner" | "seat" | null;
  two_factor_setup_needed?: boolean;
};

/**
 * The signed-in user, or null. Asks the API using the browser's session cookie.
 * Server-only. This only decides what to render; the API enforces every permission itself.
 */
export async function getCurrentUser(): Promise<User | null> {
  const cookieHeader = (await cookies()).toString();
  if (!cookieHeader) return null;
  try {
    const res = await fetch(`${apiBase()}/api/v1/auth/me`, {
      headers: await apiHeaders(),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const me = (await res.json()) as MeResponse;
    return { id: me.id, name: me.display_name, roles: me.roles, institutionRole: me.institution_role ?? null, twoFactorSetupNeeded: me.two_factor_setup_needed ?? false };
  } catch {
    return null;
  }
}
