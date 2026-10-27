<script setup lang="ts">
import { computed, onMounted } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import { useAuthStore } from "./auth";

const auth = useAuthStore();
const route = useRoute();
const isLogin = computed(() => route.path === "/login");
const name = computed(() => auth.user?.first_name || auth.user?.username || "User");
const roleLabel = computed(() => ({
  admin: "Administrator",
  supervisor: "Supervisor",
  officer: "Compliance officer",
  merchant: "Merchant",
}[auth.user?.role ?? "merchant"]));

const nav = computed(() => {
  const role = auth.user?.role;
  const items = [
    { label: "Overview", to: "/", icon: "▦", roles: ["admin", "supervisor", "officer", "merchant"] },
    { label: "Merchants", to: "/workspace/merchants", icon: "◉", roles: ["admin", "supervisor", "officer", "merchant"] },
    { label: "Declarations", to: "/workspace/declarations", icon: "▤", roles: ["admin", "supervisor", "officer", "merchant"] },
    { label: "Transactions", to: "/workspace/transactions", icon: "↗", roles: ["admin", "supervisor", "officer"] },
    { label: "Reconciliation", to: "/workspace/reconciliation", icon: "⇄", roles: ["admin", "supervisor", "officer"] },
    { label: "Risk review", to: "/workspace/risk", icon: "◈", roles: ["admin", "supervisor", "officer"] },
    { label: "Investigations", to: "/workspace/cases", icon: "▣", roles: ["admin", "supervisor", "officer"] },
    { label: "Identity review", to: "/workspace/identity", icon: "⌕", roles: ["admin", "supervisor", "officer"] },
    { label: "Social intelligence", to: "/workspace/social", icon: "◎", roles: ["admin", "supervisor", "officer"] },
    { label: "TaRMS integration", to: "/workspace/tarm", icon: "↔", roles: ["admin", "supervisor", "officer", "merchant"] },
    { label: "Import history", to: "/workspace/imports", icon: "⇧", roles: ["admin", "supervisor"] },
    { label: "Reports & exports", to: "/workspace/reports", icon: "▥", roles: ["admin", "supervisor", "officer", "merchant"] },
    { label: "Audit trail", to: "/workspace/audit", icon: "◷", roles: ["admin", "supervisor"] },
    { label: "Users & rules", to: "/workspace/admin", icon: "⚙", roles: ["admin"] },
  ];
  return items.filter((item) => role && item.roles.includes(role));
});

onMounted(() => auth.load());

async function signOut() {
  try {
    await auth.logout();
    window.location.assign("/login");
  } catch (error) {
    console.error(error);
  }
}
</script>

<template>
  <RouterView v-if="isLogin || !auth.user" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <RouterLink to="/" class="brand">
        <span class="brand-mark">T</span>
        <span><strong>TMCIS</strong><small>INTELLIGENCE</small></span>
      </RouterLink>
      <div class="workspace-label">WORKSPACE</div>
      <nav class="side-nav" aria-label="Main navigation">
        <RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="nav-link">
          <span class="nav-icon">{{ item.icon }}</span><span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <div class="demo-chip"><span class="live-dot"></span> SIMULATED ENVIRONMENT</div>
        <p>All displayed financial, taxpayer, and social records are fictional.</p>
      </div>
    </aside>
    <main class="main-area">
      <header class="topbar">
        <div class="breadcrumb">TMCIS <span>/</span> {{ route.path === "/" ? "Overview" : route.params.module }}</div>
        <div class="user-menu">
          <span class="role-pill">{{ roleLabel }}</span>
          <div class="avatar">{{ name.slice(0, 1).toUpperCase() }}</div>
          <div class="user-identity"><strong>{{ name }}</strong><small>{{ auth.user?.username }}</small></div>
          <button class="icon-button" title="Sign out" aria-label="Sign out" @click="signOut">↪</button>
        </div>
      </header>
      <section class="content-area">
        <RouterView />
      </section>
    </main>
  </div>
</template>
