import { create } from "zustand";

interface AuthStore {
  isAuthenticated: boolean;
  userId: string;
  setAuth: (userId: string) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  isAuthenticated: false,
  userId: "",
  setAuth: (userId) => {
    set({ isAuthenticated: true, userId });
  },
  clearAuth: () => {
    set({ isAuthenticated: false, userId: "" });
  },
}));
