import { create } from "zustand";
import { persist } from "zustand/middleware";
import { setAccessToken } from "@/lib/api/client";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  setAuth: (user: User, accessToken: string, refreshToken: string) => void;
  clearAuth: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,

      setAuth: (user, accessToken, refreshToken) => {
        setAccessToken(accessToken);
        set({ user, accessToken, refreshToken });
      },

      clearAuth: () => {
        setAccessToken(null);
        set({ user: null, accessToken: null, refreshToken: null });
      },

      isAuthenticated: () => !!get().accessToken && !!get().user,
    }),
    {
      name: "prospectOS-auth",
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.accessToken) {
          setAccessToken(state.accessToken);
        }
      },
    }
  )
);
