import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Terminal design tokens
        bg: "var(--color-bg)",
        "surface-new": "var(--color-surface)",
        "surface-2": "var(--color-surface-2)",
        border: "var(--color-border)",
        "border-2": "var(--color-border-2)",
        text: "var(--color-text)",
        text2: "var(--color-text-2)",
        text3: "var(--color-text-3)",
        text4: "var(--color-text-4)",
        accent: "var(--color-accent)",
        accent2: "var(--color-accent-2)",
        "accent-dim": "var(--color-accent-dim)",
        success: "var(--color-success)",
        "success-dim": "var(--color-success-dim)",
        warning: "var(--color-warning)",
        "warning-dim": "var(--color-warning-dim)",
        danger: "var(--color-danger)",
        "danger-dim": "var(--color-danger-dim)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
