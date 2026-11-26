import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--c-${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        "surface-2": token("surface2"),
        line: token("border"),
        fg: token("fg"),
        muted: token("muted"),
        accent: token("accent"),
        "accent-fg": token("accentfg"),
        "accent-soft": token("accentsoft"),
        danger: token("danger"),
        success: token("success"),
        "hand-left": token("left"),
        "hand-right": token("right"),
        "key-white": token("keywhite"),
        "key-black": token("keyblack"),
        "key-ink": token("keyink"),
        "key-ink-black": token("keyinkblack"),
        dot: token("dot"),
        "dot-soft": token("dotsoft"),
      },
      keyframes: {
        // A slow ring that grows and fades, about one pulse every two seconds. Well under the
        // three-flashes-a-second limit (WCAG 2.3.1), and switched off for reduced motion.
        "subscribe-pulse": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgb(var(--c-accent) / 0.55)" },
          "60%": { boxShadow: "0 0 0 10px rgb(var(--c-accent) / 0)" },
        },
      },
      animation: { "subscribe-pulse": "subscribe-pulse 2s ease-out infinite" },
      fontFamily: {
        sans: ['"Schibsted Grotesk Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
