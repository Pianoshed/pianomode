const WHITE_PCS = [0, 2, 4, 5, 7, 9, 11];
const BLACK_AFTER: Record<number, number> = { 0: 1, 1: 3, 3: 6, 4: 8, 5: 10 }; // white index -> pitch class

/**
 * Decorative piano keys (not the playable keyboard). `highlight` holds pitch classes (0 = C).
 * Used for the logo mark and the landing page; the real 88-key piano is a separate component.
 */
export function KeyStrip({
  octaves = 1,
  highlight = [],
  className = "",
}: {
  octaves?: number;
  highlight?: readonly number[];
  className?: string;
}) {
  const whiteCount = octaves * 7;
  const w = 100 / whiteCount;
  const keys = [];
  for (let i = 0; i < whiteCount; i++) {
    const pc = WHITE_PCS[i % 7] as number;
    keys.push(
      <rect
        key={`w${i}`}
        x={i * w + 0.3}
        y={0}
        width={w - 0.6}
        height={100}
        rx={2}
        className={highlight.includes(pc) ? "fill-accent" : "fill-surface stroke-line"}
        strokeWidth={0.6}
      />,
    );
  }
  for (let i = 0; i < whiteCount; i++) {
    const pc = BLACK_AFTER[i % 7];
    if (pc === undefined) continue;
    keys.push(
      <rect
        key={`b${i}`}
        x={(i + 1) * w - w * 0.3}
        y={0}
        width={w * 0.6}
        height={62}
        rx={1.5}
        className={highlight.includes(pc) ? "fill-accent" : "fill-fg"}
      />,
    );
  }
  return (
    <svg
      aria-hidden
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className={className}
      focusable="false"
    >
      {keys}
    </svg>
  );
}
