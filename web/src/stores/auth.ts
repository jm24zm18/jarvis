import { create } from "zustand";

interface AuthStore {
  isAuthenticated: boolean;
  userId: string;
  role: string;
  setAuth: (userId: string, role: string) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  isAuthenticated: false,
  userId: "",
  role: "user",
  setAuth: (userId, role) => {
    set({ isAuthenticated: true, userId, role });
  },
  clearAuth: () => {
    set({ isAuthenticated: false, userId: "", role: "user" });
  },
}));
