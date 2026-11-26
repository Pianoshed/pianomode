"use client";

import { Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The pulsing "Subscribe" button. It pulses slowly and stops for people who ask their device
 * for reduced motion, and while the pointer or keyboard focus is on it. Hidden on the
 * Subscription pages themselves, where it would only point at where you already are.
 */
export function SubscribeButton({ label, compact = false }: { label: string; compact?: boolean }) {
  const pathname = usePathname();
  if (pathname.startsWith("/subscription")) return null;
  return (
    <Link
      href="/subscription"
      className={`inline-flex items-center justify-center gap-2 rounded-lg bg-accent font-semibold text-accent-fg animate-subscribe-pulse hover:animate-none focus-visible:animate-none motion-reduce:animate-none ${
        compact ? "min-h-11 px-3 text-sm" : "min-h-12 w-full px-4 text-base"
      }`}
    >
      <Sparkles aria-hidden className="h-4 w-4 shrink-0" />
      {label}
    </Link>
  );
}
