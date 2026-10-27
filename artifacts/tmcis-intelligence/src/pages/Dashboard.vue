<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api } from "../api";
import { useAuthStore } from "../auth";

const auth = useAuthStore();
const data = ref<any>(null);
const error = ref("");
const loading = ref(true);
const displayName = computed(() => auth.user?.first_name || auth.user?.username || "there");
const roleTitle = computed(() => ({
  admin: "System overview",
  supervisor: "Department overview",
  officer: "My assigned work",
  merchant: "Your account overview",
}[auth.user?.role ?? "merchant"]));
const maxSourceTotal = computed(() => Math.max(1, ...(data.value?.source_totals ?? []).map((item: any) => Number(item.total || 0))));

onMounted(async () => {
  try {
    data.value = await api("/dashboard");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Dashboard data could not be loaded.";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">TUESDAY, OCTOBER 27, 2026 · FICTIONAL DEMO DATA</div>
      <h1>{{ roleTitle }}</h1>
      <p>Good to see you, {{ displayName }}. Here is the latest activity in your workspace.</p>
    </div>
    <div class="heading-actions"><span class="system-state"><i></i> Simulated sources online</span></div>
  </div>
  <div v-if="error" class="alert alert-error">{{ error }}</div>
  <div v-if="loading" class="loading-row"><span class="spinner"></span> Loading current records…</div>
  <template v-else-if="data">
    <div class="metric-grid">
      <article class="metric-card">
        <div class="metric-top"><span>Declarations</span><span class="metric-icon teal">▤</span></div>
        <strong>{{ data.declarations }}</strong>
        <small>{{ data.submitted_declarations }} submitted for review</small>
      </article>
      <article class="metric-card">
        <div class="metric-top"><span>Transactions</span><span class="metric-icon blue">↗</span></div>
        <strong>{{ data.transactions }}</strong>
        <small>Records from simulated sources</small>
      </article>
      <article class="metric-card">
        <div class="metric-top"><span>Open cases</span><span class="metric-icon amber">▣</span></div>
        <strong>{{ data.open_cases }}</strong>
        <small>{{ data.overdue_cases }} overdue for review</small>
      </article>
      <article class="metric-card">
        <div class="metric-top"><span>Review exceptions</span><span class="metric-icon rose">⌕</span></div>
        <strong>{{ data.reconciliation_exceptions }}</strong>
        <small>Need a human decision</small>
      </article>
    </div>
    <div class="dashboard-grid">
      <section class="panel">
        <div class="panel-heading">
          <div><h2>Transaction activity</h2><p>Source totals calculated from saved records</p></div>
          <RouterLink to="/workspace/transactions" class="link-button">View records <span>→</span></RouterLink>
        </div>
        <div v-if="!data.source_totals?.length" class="empty-state">No transaction records are available for this account.</div>
        <div v-else class="source-bars">
          <div v-for="source in data.source_totals" :key="source.source__code" class="source-row">
            <div class="source-label"><span>{{ source.source__name }}</span><strong>{{ source.count }}</strong></div>
            <div class="bar-track"><span :style="{ width: `${Math.max(4, Number(source.total || 0) / maxSourceTotal * 100)}%` }"></span></div>
            <small>{{ source.total ?? 0 }} total</small>
          </div>
        </div>
        <div class="fictional-note">Source categories are illustrative. Demo transactions are not bank or mobile-money records.</div>
      </section>
      <section class="panel">
        <div class="panel-heading">
          <div><h2>Recent cases</h2><p>Cases visible to your role</p></div>
          <RouterLink to="/workspace/cases" class="link-button">Open queue <span>→</span></RouterLink>
        </div>
        <div v-if="!data.recent_cases?.length" class="empty-state">No cases are assigned or available.</div>
        <div v-else class="activity-list">
          <div v-for="item in data.recent_cases" :key="item.id" class="activity-item">
            <span class="activity-mark">C</span>
            <div class="activity-copy"><strong>{{ item.reference }} · {{ item.merchant__business_name }}</strong><small>{{ item.assigned_officer__username || "Unassigned" }}</small></div>
            <span class="status-tag" :class="item.status">{{ item.status.replaceAll("_", " ") }}</span>
          </div>
        </div>
      </section>
    </div>
    <section class="notice-banner">
      <span class="notice-icon">i</span>
      <div><strong>Review indicators are not findings.</strong><p>Scores and mismatches are explainable decision-support signals. They do not establish wrongdoing and require authorized human review.</p></div>
      <RouterLink to="/workspace/risk" class="link-button">Risk methodology <span>→</span></RouterLink>
    </section>
  </template>
</template>
