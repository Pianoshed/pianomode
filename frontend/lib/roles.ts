export type Role = "learner" | "educator" | "admin";

export type User = {
  id: string;
  name: string;
  roles: Role[];
  /** "owner" manages an institution's logins; "seat" is a login that institution handed out. */
  institutionRole?: "owner" | "seat" | null;
  /** An administrator on a site that requires two-factor, who has not turned it on yet. */
  twoFactorSetupNeeded?: boolean;
};

export function hasAnyRole(user: User | null, roles: readonly Role[]): boolean {
  return user !== null && user.roles.some((r) => roles.includes(r));
}
