import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: "var(--text-primary)",
        mist: "var(--bg-mist)",
        ember: "#f46036",
        leaf: "#1b998b",
        surface: "var(--bg-surface)",
        elevated: "var(--bg-elevated)",
      },
      fontFamily: {
        display: ["Space Grotesk", "ui-sans-serif", "sans-serif"],
        body: ["Manrope", "ui-sans-serif", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
