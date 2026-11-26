import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";
import "@fontsource-variable/schibsted-grotesk";
import "./globals.css";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: { default: "Keystudy", template: "%s · Keystudy" },
  description: "A piano practice workspace: keyboard, lessons, MIDI and chord analysis.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Per-request nonce from middleware.ts. Reading it makes pages render per request.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-dvh bg-bg font-sans text-fg antialiased">{children}</body>
    </html>
  );
}
