import Link from "next/link";
import { Brand } from "@/components/Brand";
import { KeyStrip } from "@/components/KeyStrip";
import { LegalLinks } from "@/components/legal/LegalLinks";
import { buttonStyles } from "@/components/ui/button";

export default function LandingPage() {
  return (
    <div className="mx-auto flex min-h-dvh max-w-5xl flex-col px-6 py-6 sm:px-8">
      <header>
        <Brand href="/" />
      </header>
      <main className="flex flex-1 flex-col justify-center gap-8 py-16">
        <div className="max-w-2xl">
          <h1 className="text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-6xl">
            See the notes. Hear them. Play them again.
          </h1>
          <p className="mt-5 max-w-[56ch] text-lg text-muted">
            A piano practice workspace that puts chords and melodies on a keyboard, so you can learn
            by watching and listening.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/dashboard" className={buttonStyles({ size: "lg" })}>
              Open the app
            </Link>
            <Link href="/register" className={buttonStyles({ variant: "secondary", size: "lg" })}>
              Create account
            </Link>
          </div>
        </div>
        <KeyStrip octaves={3} highlight={[0, 4, 7]} className="h-40 w-full sm:h-56" />
      </main>
      <footer className="pt-6"><LegalLinks /></footer>
    </div>
  );
}
