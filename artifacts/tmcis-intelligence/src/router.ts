import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "./auth";
import { createPinia } from "pinia";
import SignIn from "./pages/SignIn.vue";
import Dashboard from "./pages/Dashboard.vue";
import Workspace from "./pages/Workspace.vue";

const pinia = createPinia();

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/login", component: SignIn, meta: { public: true } },
    { path: "/", component: Dashboard },
    { path: "/workspace/:module", component: Workspace },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach(async (to) => {
  const auth = useAuthStore(pinia);
  await auth.load();
  if (to.meta.public) {
    if (auth.user && to.path === "/login") return "/";
    return true;
  }
  if (!auth.user) return "/login";
  return true;
});

export { pinia };
