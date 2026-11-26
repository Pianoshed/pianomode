import Link from "next/link";
import { buttonStyles } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-dvh max-w-xl flex-col items-start justify-center gap-4 px-6">
      <h1 className="text-3xl font-extrabold tracking-tight">Page not found</h1>
      <p className="text-muted">The page you opened does not exist, or you do not have access to it.</p>
      <Link href="/dashboard" className={buttonStyles()}>
        Go to dashboard
      </Link>
    </div>
  );
}
