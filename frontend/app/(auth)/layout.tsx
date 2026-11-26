import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { Brand } from "@/components/Brand";
import { LegalLinks } from "@/components/legal/LegalLinks";
import { getCurrentUser } from "@/lib/user";

export default async function AuthLayout({ children }: { children: ReactNode }) {
  if (await getCurrentUser()) redirect("/dashboard");
  return (
    <div className="mx-auto flex min-h-dvh max-w-5xl flex-col px-6 py-6 sm:px-8">
      <header>
        <Brand href="/" />
      </header>
      <main className="flex flex-1 items-center justify-center py-10">{children}</main>
      <footer><LegalLinks /></footer>
    </div>
  );
}
