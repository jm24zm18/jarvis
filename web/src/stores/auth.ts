import { create } from "zustand";

interface AuthStore {
  token: string;
  userId: string;
  setAuth: (token: string, userId: string) => void;
  clearAuth: () => void;
}

const savedToken = localStorage.getItem("jarvis.token") ?? "";
const savedUserId = localStorage.getItem("jarvis.user_id") ?? "";

export const useAuthStore = create<AuthStore>((set) => ({
  token: savedToken,
  userId: savedUserId,
  setAuth: (token, userId) => {
    localStorage.setItem("jarvis.token", token);
    localStorage.setItem("jarvis.user_id", userId);
    set({ token, userId });
  },
  clearAuth: () => {
    localStorage.removeItem("jarvis.token");
    localStorage.removeItem("jarvis.user_id");
    set({ token: "", userId: "" });
  },
}));
