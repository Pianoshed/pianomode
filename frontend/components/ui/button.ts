export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition-colors disabled:opacity-50 disabled:pointer-events-none";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent/90",
  secondary: "border border-line bg-surface text-fg hover:bg-surface-2",
  ghost: "text-fg hover:bg-surface-2",
};

const sizes: Record<ButtonSize, string> = {
  md: "min-h-11 px-4 text-sm",
  lg: "min-h-12 px-6 text-base",
};

/** Class names for anything that should look like a button (<button>, <Link>, <a>). */
export function buttonStyles(opts: { variant?: ButtonVariant; size?: ButtonSize } = {}): string {
  const { variant = "primary", size = "md" } = opts;
  return `${base} ${variants[variant]} ${sizes[size]}`;
}
