import type { Config } from "tailwindcss";

/**
 * Praxis Console design tokens.
 * Ground: cool slate ink (blue-biased neutral, deliberately not pure grey).
 * Accent: iris (flat, echoes Linear's indigo identity — the one bold hue).
 * Data:   aqua (reserved for learning/delta visualizations).
 * State:  ok / warn / bad — semantic, kept separate from the accent.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0A0C12",
        surface: "#11141D",
        "surface-2": "#161B27",
        raised: "#1B2130",
        line: "#232A3A",
        "line-soft": "#1A2030",
        text: "#E9EDF5",
        dim: "#9AA5B8",
        faint: "#5C6678",
        iris: "#7B8CFF",
        "iris-dim": "#2A3052",
        aqua: "#4FD0C8",
        ok: "#46B98A",
        warn: "#E0A33C",
        bad: "#F0586E",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        DEFAULT: "8px",
        sm: "6px",
        md: "10px",
        lg: "14px",
      },
      letterSpacing: {
        label: "0.08em",
      },
      maxWidth: {
        content: "1120px",
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.02) inset, 0 8px 24px -16px rgba(0,0,0,0.6)",
        glow: "0 0 0 1px rgba(123,140,255,0.35), 0 0 28px -8px rgba(123,140,255,0.45)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.4s cubic-bezier(0.22,0.61,0.36,1) both",
        sweep: "sweep 1.1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
