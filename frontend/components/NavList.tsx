"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NavIcon } from "@/components/NavIcon";
import { hrefFor, type NavSection } from "@/lib/nav";

export function NavList({
  sections,
  onNavigate,
}: {
  sections: NavSection[];
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main">
      {sections.map((section, idx) => (
        <ul
          key={section.id}
          className={idx === 0 ? "space-y-1" : "mt-3 space-y-1 border-t border-line pt-3"}
        >
          {section.items.map((item) => {
            const href = hrefFor(item);
            const current = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <li key={item.slug}>
                <Link
                  href={href}
                  onClick={onNavigate}
                  aria-current={current ? "page" : undefined}
                  className={`flex min-h-11 items-center gap-3 rounded-lg border-l-4 px-3 text-sm font-medium transition-colors ${
                    current
                      ? "border-accent bg-accent-soft text-fg"
                      : "border-transparent text-muted hover:bg-surface-2 hover:text-fg"
                  }`}
                >
                  <NavIcon name={item.icon} />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      ))}
    </nav>
  );
}
