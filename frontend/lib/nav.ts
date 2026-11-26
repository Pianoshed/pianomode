import { hasAnyRole, type Role, type User } from "@/lib/roles";

export type IconName =
  | "dashboard"
  | "piano"
  | "learn"
  | "progressions"
  | "theory"
  | "midi"
  | "audio"
  | "practice"
  | "library"
  | "subscription"
  | "institution"
  | "billingAdmin"
  | "people"
  | "settings"
  | "admin";

export type NavItem = {
  slug: string;
  label: string;
  icon: IconName;
  /** One plain sentence on what this area is for. */
  summary: string;
  /** Roles allowed to see and open it. Omitted means everyone. */
  roles?: readonly Role[];
  /** Only people who manage an institution's logins see and open it. */
  institutionOwnerOnly?: boolean;
};

export type NavSection = { id: string; items: NavItem[] };

const ADMIN_ROLES: readonly Role[] = ["educator", "admin"];
const ADMIN_ONLY: readonly Role[] = ["admin"];

export const NAV_SECTIONS: readonly NavSection[] = [
  {
    id: "home",
    items: [
      {
        slug: "dashboard",
        label: "Dashboard",
        icon: "dashboard",
        summary: "Pick up where you left off.",
      },
    ],
  },
  {
    id: "play",
    items: [
      {
        slug: "piano",
        label: "Interactive Piano",
        icon: "piano",
        summary: "An 88-key keyboard you can play, with chords and notes shown on the keys.",
      },
      {
        slug: "practice",
        label: "Practice Room",
        icon: "practice",
        summary: "Loop a passage and slow it down until it is comfortable.",
      },
    ],
  },
  {
    id: "learn",
    items: [
      {
        slug: "learn",
        label: "Learn",
        icon: "learn",
        summary: "Lessons from beginner to advanced.",
      },
      {
        slug: "progressions",
        label: "Chord Progressions",
        icon: "progressions",
        summary: "Practise chord movements with voicings for both hands.",
      },
      {
        slug: "theory",
        label: "Music Theory",
        icon: "theory",
        summary: "Scales, intervals, chords and harmony, with exercises.",
      },
    ],
  },
  {
    id: "studio",
    items: [
      {
        slug: "midi",
        label: "MIDI Studio",
        icon: "midi",
        summary: "Import a MIDI file, see its notes and play it back.",
      },
      {
        slug: "audio",
        label: "Audio Analyzer",
        icon: "audio",
        summary: "Upload a recording and get estimated chords you can review and correct.",
      },
    ],
  },
  {
    id: "account",
    items: [
      {
        slug: "library",
        label: "My Library",
        icon: "library",
        summary: "Your saved progressions, MIDI files and analyses.",
      },
      {
        slug: "subscription",
        label: "Subscription",
        icon: "subscription",
        summary: "Your plan, trial time and billing.",
      },
      {
        slug: "institution",
        label: "Institution Logins",
        icon: "institution",
        summary: "Give each person at your school or studio their own login.",
        institutionOwnerOnly: true,
      },
      {
        slug: "settings",
        label: "Account Settings",
        icon: "settings",
        summary: "Your profile and display preferences.",
      },
    ],
  },
  {
    id: "admin",
    items: [
      {
        slug: "admin",
        label: "Content Admin",
        icon: "admin",
        summary: "Create, validate and publish lessons and chord movements.",
        roles: ADMIN_ROLES,
      },
      {
        slug: "people",
        label: "People",
        icon: "people",
        summary: "Find an account, see its plan, close it, change roles and read the audit log.",
        roles: ADMIN_ONLY,
      },
      {
        slug: "billing-admin",
        label: "Billing Admin",
        icon: "billingAdmin",
        summary: "Look up a customer, record a bank transfer and see recent payments.",
        roles: ADMIN_ONLY,
      },
    ],
  },
];

export function canAccess(item: NavItem, user: User | null): boolean {
  if (item.institutionOwnerOnly && user?.institutionRole !== "owner") return false;
  return item.roles === undefined || hasAnyRole(user, item.roles);
}

/** Sections the given user may see. Sections left with no items are dropped. */
export function navSectionsFor(user: User | null): NavSection[] {
  return NAV_SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((i) => canAccess(i, user)),
  })).filter((s) => s.items.length > 0);
}

export function findNavItem(slug: string): NavItem | undefined {
  for (const s of NAV_SECTIONS) {
    const hit = s.items.find((i) => i.slug === slug);
    if (hit) return hit;
  }
  return undefined;
}

export function hrefFor(item: NavItem): string {
  return `/${item.slug}`;
}
