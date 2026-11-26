import type { ReactNode } from "react";
import { Brand } from "@/components/Brand";

export default function LegalLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col px-6 py-6 sm:px-8">
      <header>
        <Brand href="/" />
      </header>
      <main className="flex-1 py-10">{children}</main>
    </div>
  );
}
