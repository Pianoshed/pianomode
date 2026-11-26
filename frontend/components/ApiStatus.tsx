type Ready = { status: string; checks: Record<string, string> };

async function fetchReady(): Promise<Ready | null> {
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/health/ready`, { cache: "no-store" });
    return (await res.json()) as Ready;
  } catch {
    return null;
  }
}

export default async function ApiStatus() {
  const ready = await fetchReady();
  const ok = ready?.status === "ok";
  return (
    <p role="status" className="text-sm">
      <span
        aria-hidden
        className={`mr-2 inline-block h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
      />
      API: {ready === null ? "unreachable" : ok ? "ready" : "not ready"}
    </p>
  );
}
