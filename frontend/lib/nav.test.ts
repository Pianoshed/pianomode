import { describe, expect, it } from "vitest";
import { canAccess, findNavItem, hrefFor, NAV_SECTIONS, navSectionsFor } from "@/lib/nav";
import type { User } from "@/lib/roles";

const learner: User = { id: "1", name: "A", roles: ["learner"] };
const educator: User = { id: "2", name: "B", roles: ["educator"] };
const admin: User = { id: "3", name: "C", roles: ["admin"] };

const slugs = (u: User | null) => navSectionsFor(u).flatMap((s) => s.items.map((i) => i.slug));

describe("navigation", () => {
  it("includes every required main destination", () => {
    const all = slugs(null);
    for (const s of [
      "dashboard",
      "piano",
      "learn",
      "progressions",
      "theory",
      "midi",
      "audio",
      "practice",
      "library",
      "subscription",
      "settings",
    ]) {
      expect(all).toContain(s);
    }
  });

  it("hides admin navigation from signed-out users and learners", () => {
    expect(slugs(null)).not.toContain("admin");
    expect(slugs(learner)).not.toContain("admin");
  });

  it("shows admin navigation to educators and admins", () => {
    expect(slugs(educator)).toContain("admin");
    expect(slugs(admin)).toContain("admin");
  });

  it("denies direct access to admin items for unauthorised users", () => {
    const item = findNavItem("admin");
    expect(item).toBeDefined();
    expect(canAccess(item!, null)).toBe(false);
    expect(canAccess(item!, learner)).toBe(false);
    expect(canAccess(item!, admin)).toBe(true);
  });

  it("shows Institution Logins only to people who manage an institution", () => {
    const owner: User = { ...learner, institutionRole: "owner" };
    const seat: User = { ...learner, institutionRole: "seat" };
    expect(slugs(owner)).toContain("institution");
    expect(slugs(seat)).not.toContain("institution");
    expect(slugs(learner)).not.toContain("institution");
    expect(slugs(null)).not.toContain("institution");
    expect(canAccess(findNavItem("institution")!, seat)).toBe(false);
  });

  it("keeps Billing Admin for admins only", () => {
    expect(slugs(admin)).toContain("billing-admin");
    expect(slugs(admin)).toContain("people");
    expect(slugs(educator)).not.toContain("people");
    expect(slugs(educator)).not.toContain("billing-admin");
    expect(slugs(learner)).not.toContain("billing-admin");
    expect(canAccess(findNavItem("billing-admin")!, educator)).toBe(false);
  });

  it("has unique slugs and hrefs", () => {
    const all = NAV_SECTIONS.flatMap((s) => s.items);
    expect(new Set(all.map((i) => i.slug)).size).toBe(all.length);
    expect(new Set(all.map(hrefFor)).size).toBe(all.length);
  });

  it("returns undefined for unknown slugs", () => {
    expect(findNavItem("nope")).toBeUndefined();
  });
});
