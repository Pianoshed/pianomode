const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Seven small bars, one per day, with the total in words (the bars alone would not be readable by a screen reader). */
export function ActivityBars({ days, total }: { days: { date: string; count: number }[]; total: number }) {
  const max = Math.max(1, ...days.map((d) => d.count));
  return (
    <div className="space-y-3">
      <p className="text-2xl font-bold">
        {total} {total === 1 ? "answer or pass" : "answers and passes"} <span className="text-base font-medium text-muted">in the last 7 days</span>
      </p>
      <ul className="flex h-20 items-end gap-2" aria-label="Activity by day">
        {days.map((d) => {
          const day = WEEKDAY[new Date(`${d.date}T12:00:00Z`).getUTCDay()];
          return (
            <li key={d.date} className="flex h-full flex-1 flex-col items-center justify-end gap-1" title={`${day}: ${d.count}`}>
              <span className="w-full rounded-t bg-accent" style={{ height: `${Math.max(d.count ? 8 : 2, (d.count / max) * 100)}%`, opacity: d.count ? 1 : 0.25 }} />
              <span className="text-xs text-muted">{day}</span>
              <span className="sr-only">{d.count}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
