import Link from "next/link";

export function LegalLinks({ className = "" }: { className?: string }) {
  return (
    <nav aria-label="Legal" className={`flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted ${className}`}>
      <Link href="/terms" className="underline-offset-4 hover:underline">Terms</Link>
      <Link href="/privacy" className="underline-offset-4 hover:underline">Privacy</Link>
      <Link href="/refunds" className="underline-offset-4 hover:underline">Refunds</Link>
    </nav>
  );
}
