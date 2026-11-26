import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { Brand } from "@/components/Brand";
import { MobileBar } from "@/components/MobileBar";
import { NavList } from "@/components/NavList";
import { SignOutButton } from "@/components/SignOutButton";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Notice } from "@/components/ui/Notice";
import { LegalLinks } from "@/components/legal/LegalLinks";
import { SubscribeButton } from "@/components/billing/SubscribeButton";
import { getBillingStatus } from "@/lib/billing/server";
import { subscribeLabel } from "@/lib/billing/format";
import { navSectionsFor } from "@/lib/nav";
import { getCurrentUser } from "@/lib/user";

export async function AppShell({ children }: { children: ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const sections = navSectionsFor(user);
  const subscribe = subscribeLabel(await getBillingStatus());

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-fg"
      >
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 overflow-y-auto border-r border-line bg-bg p-4 lg:flex">
        <Brand />
        <NavList sections={sections} />
        {subscribe ? <SubscribeButton label={subscribe} /> : null}
        <div className="mt-auto space-y-3">
          <LegalLinks className="px-1" />
          <SignOutButton name={user.name} />
          <ThemeToggle />
        </div>
      </aside>
      <div className="min-w-0">
        <MobileBar sections={sections} userName={user.name} subscribe={subscribe} />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-8 sm:py-10">
          {user.twoFactorSetupNeeded ? (
            <div className="mb-6">
              <Notice tone="error">
                Your administrator role needs two-factor sign-in before admin tools open.{" "}
                <Link href="/settings" className="underline underline-offset-4">Turn it on in Account Settings</Link>
              </Notice>
            </div>
          ) : null}
          {children}
        </main>
      </div>
    </div>
  );
}
