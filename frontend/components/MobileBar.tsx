"use client";

import { Menu, X } from "lucide-react";
import { useRef } from "react";
import { Brand } from "@/components/Brand";
import { SubscribeButton } from "@/components/billing/SubscribeButton";
import { NavList } from "@/components/NavList";
import { SignOutButton } from "@/components/SignOutButton";
import { ThemeToggle } from "@/components/ThemeToggle";
import type { NavSection } from "@/lib/nav";

/** Top bar plus slide-in menu for screens below the `lg` breakpoint. Uses a native <dialog>, which traps focus and closes on Escape. */
export function MobileBar({
  sections,
  userName,
  subscribe,
}: {
  sections: NavSection[];
  userName: string;
  subscribe?: string | null;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const close = () => dialogRef.current?.close();

  return (
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-bg/95 px-4 py-2 backdrop-blur lg:hidden">
      <Brand />
      <div className="flex items-center gap-2">
        {subscribe ? <SubscribeButton label={subscribe.split(" (")[0] ?? subscribe} compact /> : null}
        <button
          type="button"
          aria-label="Open menu"
          onClick={() => dialogRef.current?.showModal()}
          className="flex h-11 w-11 items-center justify-center rounded-lg hover:bg-surface-2"
        >
          <Menu aria-hidden className="h-6 w-6" />
        </button>
      </div>
      <dialog
        ref={dialogRef}
        aria-label="Menu"
        onClick={(e) => {
          if (e.target === dialogRef.current) close();
        }}
        className="m-0 mr-auto h-dvh max-h-none w-72 max-w-[85vw] bg-bg p-0 text-fg backdrop:bg-black/50"
      >
        <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
          <div className="flex items-center justify-between">
            <Brand />
            <button
              type="button"
              aria-label="Close menu"
              onClick={close}
              className="flex h-11 w-11 items-center justify-center rounded-lg hover:bg-surface-2"
            >
              <X aria-hidden className="h-6 w-6" />
            </button>
          </div>
          <NavList sections={sections} onNavigate={close} />
          {subscribe ? <SubscribeButton label={subscribe} /> : null}
          <div className="mt-auto space-y-3">
            <SignOutButton name={userName} />
            <ThemeToggle />
          </div>
        </div>
      </dialog>
    </header>
  );
}
