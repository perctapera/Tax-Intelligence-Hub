import { defineStore } from "pinia";
import { api } from "./api";

export type AuthUser = {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  role: "admin" | "supervisor" | "officer" | "merchant";
  department?: string;
  merchant_id?: number | null;
};

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null as AuthUser | null,
    checked: false,
  }),
  actions: {
    async load() {
      if (this.checked) return;
      try {
        await api("/auth/csrf");
        this.user = await api<AuthUser>("/auth/me");
      } catch {
        this.user = null;
      } finally {
        this.checked = true;
      }
    },
    async login(username: string, password: string) {
      await api("/auth/csrf");
      const result = await api<{ user: AuthUser }>("/auth/login", {
        method: "POST",
        body: { username, password },
      });
      this.user = result.user;
      this.checked = true;
    },
    async register(data: Record<string, string>) {
      await api("/auth/csrf");
      const result = await api<{ user: AuthUser }>("/auth/register", {
        method: "POST",
        body: data,
      });
      this.user = await api<AuthUser>("/auth/me").catch(() => result.user);
      this.checked = true;
    },
    async logout() {
      await api("/auth/logout", { method: "POST" });
      this.user = null;
    },
  },
});
