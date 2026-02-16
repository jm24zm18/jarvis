import { create } from "zustand";

type Theme = "light" | "dark" | "system";

interface ThemeStore {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

function getEffective(theme: Theme): "light" | "dark" {
  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return theme;
}

function applyTheme(theme: Theme) {
  const effective = getEffective(theme);
  document.documentElement.classList.toggle("dark", effective === "dark");
}

const saved = (localStorage.getItem("jarvis.theme") as Theme) || "system";
applyTheme(saved);

export const useThemeStore = create<ThemeStore>((set) => ({
  theme: saved,
  setTheme: (theme) => {
    localStorage.setItem("jarvis.theme", theme);
    applyTheme(theme);
    set({ theme });
  },
}));

// Listen for OS theme changes when in system mode
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  const current = useThemeStore.getState().theme;
  if (current === "system") {
    applyTheme("system");
  }
});
