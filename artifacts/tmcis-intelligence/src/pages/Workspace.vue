<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { API_BASE, api, rows } from "../api";
import { useAuthStore } from "../auth";

const route = useRoute();
const auth = useAuthStore();
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const payload = ref<any>(null);
const extras = ref<any>({});
const search = ref("");
const showForm = ref(false);
const selectedMerchant = ref("");
const selectedDeclaration = ref("");
const lastTarmCheck = ref<any>(null);
const transferPreview = ref<any>(null);
const assigningCase = ref<any>(null);
const assignOfficerId = ref("");
const reviewMerchantId = ref("");
const selectedFile = ref<File | null>(null);
const sourceCode = ref("");
const platformFilter = ref("");
const authUser = computed(() => auth.user);
const moduleKey = computed(() => String(route.params.module ?? ""));

const titles: Record<string, { title: string; description: string; endpoint: string }> = {
  merchants: { title: "Merchant records", description: "Search and review authorized merchant profiles.", endpoint: "/merchants" },
  declarations: { title: "Declarations", description: "Prepare, submit, and track tax declarations.", endpoint: "/declarations" },
  transactions: { title: "External financial data", description: "Inspect masked, provenance-labelled transaction records.", endpoint: "/transactions" },
  reconciliation: { title: "Reconciliation", description: "Compare submitted declarations with available source records.", endpoint: "/reconciliation" },
  risk: { title: "Risk assessments", description: "Explainable review indicators with historical rule versions.", endpoint: "/risk-assessments" },
  cases: { title: "Investigations", description: "Manage assignments, findings, supervisory decisions, and case history.", endpoint: "/cases" },
  identity: { title: "Identity resolution", description: "Review candidate links; records are never merged automatically.", endpoint: "/identity-candidates" },
  social: { title: "Social intelligence", description: "Review manually entered or CSV-imported public business leads.", endpoint: "/social-leads" },
  tarm: { title: "TaRMS integration", description: "Use the clearly labelled simulated adapter for checks, links, and transfers.", endpoint: "/tarm/status" },
  imports: { title: "Import history", description: "Inspect accepted, rejected, and duplicate import rows.", endpoint: "/imports" },
  audit: { title: "Audit trail", description: "Review recorded actions available to your role.", endpoint: "/audit" },
  reports: { title: "Reports & exports", description: "Download authorized records in CSV format.", endpoint: "/dashboard" },
  admin: { title: "Users & configuration", description: "Manage development accounts and review versioned risk rules.", endpoint: "/admin/users" },
};

const page = computed(() => titles[moduleKey.value] ?? titles.merchants);
const list = computed<any[]>(() => {
  if (moduleKey.value === "tarm") return rows(payload.value?.recent_transfers ?? []);
  return rows(payload.value);
});
const columns = computed(() => ({
  merchants: ["business_name", "tin", "business_type", "status", "city"],
  declarations: ["reference", "merchant_name", "merchant_tin", "period", "declared_revenue", "currency", "status"],
  transactions: ["reference", "source_name", "tin", "transaction_at", "amount", "currency", "reconciliation_status"],
  reconciliation: ["declaration_reference", "merchant_name", "status", "declared_amount", "observed_amount", "amount_difference"],
  risk: ["merchant_name", "merchant_tin", "score", "band", "created_at"],
  cases: ["reference", "merchant_name", "priority", "status", "assigned_officer_username", "due_date"],
  identity: ["merchant_name", "candidate_name", "reason", "status"],
  social: ["reference", "platform", "profile_name", "review_status", "linked_merchant_name", "collection_method"],
  tarm: ["reference", "merchant_name", "declaration_reference", "status", "environment", "created_at"],
  imports: ["source", "file_name", "accepted", "rejected", "duplicates", "status", "created_at"],
  audit: ["actor_username", "action", "entity_type", "entity_id", "created_at"],
  admin: ["username", "email", "role", "department"],
}[moduleKey.value] ?? ["id"]));

const merchantName = (item: any) => item.business_name || item.name || "—";
const fieldTitle = (field: string) =>
  field.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const displayValue = (item: any, field: string) => {
  if (field === "business_name") return merchantName(item);
  const value = item[field];
  if (value === null || value === undefined || value === "") return "—";
  if (field === "triggered_rules") return `${Array.isArray(value) ? value.length : 0} rules`;
  if (field.endsWith("_at") || field === "created_at" || field === "due_date") {
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleDateString();
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

const canCreate = computed(() => {
  if (moduleKey.value === "declarations") return true;
  if (moduleKey.value === "merchants" || moduleKey.value === "cases") {
    return ["admin", "supervisor"].includes(authUser.value?.role ?? "");
  }
  if (moduleKey.value === "social") return ["admin", "supervisor", "officer"].includes(authUser.value?.role ?? "");
  if (moduleKey.value === "transactions") return ["admin", "supervisor", "officer"].includes(authUser.value?.role ?? "");
  return false;
});
const canEditProfile = computed(() => moduleKey.value === "merchants" && authUser.value?.role === "merchant");
const showActionButton = computed(() => canCreate.value || canEditProfile.value);

const form = ref<Record<string, string>>({});

async function load() {
  loading.value = true;
  error.value = "";
  transferPreview.value = null;
  try {
    const params = new URLSearchParams();
    if (search.value.trim() && moduleKey.value !== "tarm" && moduleKey.value !== "admin") {
      params.set("q", search.value.trim());
    }
    if (moduleKey.value === "social" && platformFilter.value) params.set("platform", platformFilter.value);
    if (moduleKey.value === "transactions" && sourceCode.value) params.set("source", sourceCode.value);
    if (moduleKey.value === "reconciliation" && platformFilter.value) params.set("status", platformFilter.value);
    const query = params.toString() ? `?${params.toString()}` : "";
    const endpoint = moduleKey.value === "risk" && authUser.value?.role === "admin"
      ? "/risk-assessments"
      : page.value.endpoint;
    payload.value = await api(`${endpoint}${query}`);
    if (moduleKey.value === "merchants" && authUser.value?.role === "merchant" && !showForm.value) {
      const ownProfile: any = rows(payload.value)[0];
      if (ownProfile) {
        form.value = {
          name: ownProfile.name ?? "",
          business_name: ownProfile.business_name ?? "",
          business_type: ownProfile.business_type ?? "",
          email: ownProfile.email ?? "",
          phone: ownProfile.phone ?? "",
          address: ownProfile.address ?? "",
          city: ownProfile.city ?? "",
        };
      }
    }
    if (["merchants", "risk", "cases", "social", "tarm", "declarations", "transactions", "admin"].includes(moduleKey.value)) {
      const [merchantResult, declarationResult] = await Promise.all([
        api("/merchants?page_size=100").catch(() => ({ results: [] })),
        api("/declarations?page_size=100").catch(() => ({ results: [] })),
      ]);
      extras.value.merchants = rows(merchantResult);
      extras.value.declarations = rows(declarationResult);
    }
    if (moduleKey.value === "transactions") {
      extras.value.sources = await api("/sources").catch(() => []);
      extras.value.imports = await api("/imports").catch(() => []);
    }
    if (moduleKey.value === "cases" && ["admin", "supervisor"].includes(authUser.value?.role ?? "")) {
      extras.value.officers = await api("/staff/officers").catch(() => []);
    }
    if (moduleKey.value === "admin") extras.value.riskRules = await api("/risk-rules").catch(() => []);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Records could not be loaded.";
  } finally {
    loading.value = false;
  }
}

watch([moduleKey, platformFilter], () => {
  notice.value = "";
  load();
});
onMounted(load);

function resetForm() {
  form.value = {};
  showForm.value = false;
  selectedFile.value = null;
}

async function createRecord() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    if (moduleKey.value === "merchants") {
      await api("/merchants", { method: "POST", body: form.value });
      notice.value = "Merchant record created.";
    } else if (moduleKey.value === "declarations") {
      await api("/declarations", {
        method: "POST",
        body: {
          ...form.value,
          merchant: authUser.value?.role === "merchant" ? undefined : Number(form.value.merchant),
          declared_revenue: Number(form.value.declared_revenue),
          tax_amount: Number(form.value.tax_amount),
        },
      });
      notice.value = "Declaration draft saved.";
    } else if (moduleKey.value === "transactions") {
      await api("/transactions", {
        method: "POST",
        body: {
          ...form.value,
          source: Number(form.value.source),
          amount: Number(form.value.amount),
          merchant: form.value.merchant ? Number(form.value.merchant) : null,
        },
      });
      notice.value = "Transaction saved.";
    } else if (moduleKey.value === "cases") {
      await api("/cases", {
        method: "POST",
        body: {
          ...form.value,
          merchant: Number(form.value.merchant),
          priority: form.value.priority || "normal",
        },
      });
      notice.value = "Investigation case created.";
    } else if (moduleKey.value === "social") {
      await api("/social-leads", { method: "POST", body: form.value });
      notice.value = "Social lead recorded for manual review.";
    } else if (moduleKey.value === "admin") {
      await api("/admin/users", { method: "POST", body: form.value });
      notice.value = "User account created.";
    }
    resetForm();
    await load();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "The record could not be saved.";
  } finally {
    busy.value = false;
  }
}

async function submitDeclaration(item: any) {
  await act(() => api(`/declarations/${item.id}/submit`, { method: "POST", body: {} }), "Declaration submitted.");
}

async function respondToDeclaration(item: any) {
  const response = window.prompt(item.information_request || "Add a response to the information request.");
  if (!response?.trim()) return;
  await act(
    () => api(`/declarations/${item.id}/respond`, { method: "POST", body: { response } }),
    "Response submitted to the reviewer.",
  );
}

async function reviewDeclaration(item: any, action: string) {
  const message = action === "approve" ? "" : window.prompt(
    action === "request_information" ? "What additional information is needed?" : "Why is the declaration being returned?",
  );
  if (action !== "approve" && !message?.trim()) return;
  await act(
    () => api(`/declarations/${item.id}/review`, { method: "POST", body: { action, message } }),
    action === "approve" ? "Declaration approved." : action === "return" ? "Declaration returned." : "Information request sent.",
  );
}

async function runReconciliation() {
  await act(() => api("/reconciliation/run", { method: "POST", body: {} }), "Reconciliation completed using the available records.");
}

async function resolveException(item: any) {
  const notes = window.prompt("Add a brief resolution note.");
  if (!notes?.trim()) return;
  await act(() => api(`/reconciliation/${item.id}/resolve`, { method: "POST", body: { notes } }), "Resolution note saved.");
}

async function runRisk() {
  if (!selectedMerchant.value) {
    error.value = "Select a merchant first.";
    return;
  }
  await act(
    () => api("/risk-assessments/run", { method: "POST", body: { merchant_id: Number(selectedMerchant.value) } }),
    "A new explainable assessment was saved.",
  );
}

async function decideIdentity(item: any, decision: string) {
  await act(() => api(`/identity-candidates/${item.id}`, {
    method: "PATCH",
    body: { status: decision, decision_notes: "Decision recorded by authorized reviewer." },
  }), `Candidate marked ${decision}.`);
}

async function caseTransition(item: any, nextStatus: string) {
  await act(() => api(`/cases/${item.id}/transition`, {
    method: "POST",
    body: { status: nextStatus, decision: "Reviewed in the demonstration workflow." },
  }), `Case moved to ${nextStatus.replaceAll("_", " ")}.`);
}

async function addCaseNote(item: any) {
  const body = window.prompt("Write a case note.");
  if (!body?.trim()) return;
  await act(() => api(`/cases/${item.id}/notes`, { method: "POST", body: { body } }), "Case note added.");
}

async function saveCaseAssignment(item: any) {
  if (!assignOfficerId.value) {
    error.value = "Choose an officer to assign.";
    return;
  }
  await act(() => api(`/cases/${item.id}/assign`, {
    method: "POST",
    body: { officer_id: Number(assignOfficerId.value) },
  }), "Officer assigned.");
  assigningCase.value = null;
  assignOfficerId.value = "";
}

async function reviewLead(item: any, reviewStatus: string) {
  const body: Record<string, unknown> = { review_status: reviewStatus, reviewer_comments: "Reviewed by authorized staff." };
  if (reviewStatus === "linked") {
    if (!reviewMerchantId.value) {
      error.value = "Choose a merchant before linking.";
      return;
    }
    body.linked_merchant = Number(reviewMerchantId.value);
  }
  await act(() => api(`/social-leads/${item.id}`, { method: "PATCH", body }), "Lead review saved.");
}

async function createLeadCase(item: any) {
  await act(() => api(`/social-leads/${item.id}/case`, { method: "POST", body: {} }), "Case created from reviewed lead.");
}

async function checkTin() {
  if (!selectedMerchant.value) {
    error.value = "Choose a merchant first.";
    return;
  }
  await act(async () => {
    lastTarmCheck.value = await api("/tarm/verify", {
      method: "POST",
      body: { merchant_id: Number(selectedMerchant.value) },
    });
    return lastTarmCheck.value;
  }, "TaRMS check completed in the simulated environment.");
}

async function linkTarm() {
  if (!selectedMerchant.value) return;
  await act(() => api("/tarm/link", {
    method: "POST",
    body: { merchant_id: Number(selectedMerchant.value) },
  }), "Verified taxpayer linked.");
}

async function previewTransfer() {
  if (!selectedDeclaration.value) {
    error.value = "Choose a declaration first.";
    return;
  }
  await act(async () => {
    transferPreview.value = await api("/tarm/transfers/preview", {
      method: "POST",
      body: { declaration_ids: [Number(selectedDeclaration.value)] },
    });
    return transferPreview.value;
  }, "Transfer preview is ready. Confirm only after reviewing it.");
}

async function confirmTransfer() {
  const record = transferPreview.value?.records?.find((row: any) => row.eligible);
  if (!record) {
    error.value = "There is no eligible record to transfer.";
    return;
  }
  await act(() => api("/tarm/transfers", {
    method: "POST",
    body: {
      confirm: true,
      declaration_id: record.declaration_id,
      idempotency_key: crypto.randomUUID(),
    },
  }), "Simulated transfer response recorded.");
  transferPreview.value = null;
}

async function importCsv() {
  if (!selectedFile.value) {
    error.value = "Choose a CSV file.";
    return;
  }
  const body: Record<string, unknown> = {};
  if (moduleKey.value === "transactions") body.source = sourceCode.value;
  if (moduleKey.value === "social") body.platform = platformFilter.value || form.value.platform;
  const result = await act(() => api(moduleKey.value === "social" ? "/social-leads/import" : "/transactions/import", {
    file: selectedFile.value as File,
    body,
  }), "Import completed. Review the row-level summary.");
  if (result) selectedFile.value = null;
}

async function updateRule(rule: any) {
  await act(() => api(`/risk-rules/${rule.id}`, {
    method: "PATCH",
    body: { enabled: !rule.enabled, points: rule.points },
  }), "Risk rule updated; new assessments use the saved version.");
}

async function act(action: () => Promise<any>, successMessage: string) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await action();
    notice.value = successMessage;
    await load();
    if (result?.errors?.length) error.value = `${result.rejected} row(s) rejected; inspect the import history.`;
    return result;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "The action could not be completed.";
    return null;
  } finally {
    busy.value = false;
  }
}

function download(type: string) {
  window.location.href = `${API_BASE}/export.csv?type=${encodeURIComponent(type)}`;
}

function beginProfileEdit() {
  const profile = list.value[0];
  if (!profile) return;
  form.value = {
    name: profile.name ?? "",
    business_name: profile.business_name ?? "",
    business_type: profile.business_type ?? "",
    email: profile.email ?? "",
    phone: profile.phone ?? "",
    address: profile.address ?? "",
    city: profile.city ?? "",
  };
  showForm.value = true;
}

async function saveProfile() {
  const profile = list.value[0];
  if (!profile) return;
  await act(
    () => api(`/merchants/${profile.id}`, { method: "PATCH", body: form.value }),
    "Merchant profile updated.",
  );
  showForm.value = false;
}
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">TMCIS WORKSPACE · FICTIONAL DATA</div>
      <h1>{{ page.title }}</h1>
      <p>{{ page.description }}</p>
    </div>
    <div class="heading-actions">
      <button v-if="showActionButton" class="button button-primary" @click="canEditProfile ? beginProfileEdit() : showForm = !showForm">
        {{ canEditProfile ? (showForm ? "Close form" : "Edit profile") : (showForm ? "Close form" : moduleKey === "declarations" ? "New declaration" : moduleKey === "cases" ? "Create case" : moduleKey === "social" ? "Add lead" : moduleKey === "transactions" ? "Add transaction" : moduleKey === "admin" ? "Create user" : "Add merchant") }}
        <span>{{ showForm ? "×" : "+" }}</span>
      </button>
    </div>
  </div>

  <div v-if="error" class="alert alert-error" role="alert"><span>!</span>{{ error }}<button @click="error = ''" aria-label="Dismiss error">×</button></div>
  <div v-if="notice" class="alert alert-success" role="status"><span>✓</span>{{ notice }}<button @click="notice = ''" aria-label="Dismiss message">×</button></div>

  <section v-if="moduleKey === 'reports'" class="panel report-panel">
    <div class="panel-heading"><div><h2>Authorized CSV exports</h2><p>Only records visible to your role are included.</p></div></div>
    <div class="export-grid">
      <button class="export-tile" @click="download('declarations')"><span>▤</span><strong>Declarations</strong><small>CSV · current authorized scope</small></button>
      <button v-if="authUser?.role !== 'merchant'" class="export-tile" @click="download('transactions')"><span>↗</span><strong>Transactions</strong><small>CSV · masked references</small></button>
      <button v-if="authUser?.role !== 'merchant'" class="export-tile" @click="download('cases')"><span>▣</span><strong>Investigation cases</strong><small>CSV · current authorized scope</small></button>
      <button v-if="authUser?.role !== 'merchant'" class="export-tile" @click="download('social-leads')"><span>◎</span><strong>Social intelligence</strong><small>CSV · review metadata only</small></button>
    </div>
  </section>

  <section v-if="moduleKey === 'tarm'" class="panel integration-panel">
    <div class="integration-banner">
      <span class="integration-icon">↔</span>
      <div><strong>Simulated TaRMS environment</strong><p>{{ payload?.message || "Live integration is disabled. No external system will be contacted." }}</p></div>
      <span class="status-tag success">LIVE DISABLED</span>
    </div>
    <div class="tarm-actions">
      <label>Merchant
        <select v-model="selectedMerchant">
          <option value="">Select merchant</option>
          <option v-for="merchant in extras.merchants" :key="merchant.id" :value="String(merchant.id)">{{ merchant.business_name }} · {{ merchant.tin }}</option>
        </select>
      </label>
      <button class="button button-secondary" :disabled="busy" @click="checkTin">Check TIN</button>
      <button class="button button-secondary" :disabled="busy || lastTarmCheck?.outcome !== 'registered'" @click="linkTarm">Link verified record</button>
    </div>
    <div v-if="lastTarmCheck" class="verification-result">
      <strong>{{ lastTarmCheck.outcome.replaceAll('_', ' ') }}</strong>
      <span>{{ lastTarmCheck.permitted_details?.taxpayer_name || "No permitted taxpayer detail returned." }}</span>
      <small>{{ lastTarmCheck.environment }} · {{ new Date(lastTarmCheck.verified_at).toLocaleString() }}</small>
    </div>
    <div class="transfer-box">
      <div><h3>Transfer a declaration</h3><p>Review eligible fields, confirm, and inspect the adapter response.</p></div>
      <div class="transfer-controls">
        <select v-model="selectedDeclaration"><option value="">Select declaration</option><option v-for="item in extras.declarations" :key="item.id" :value="String(item.id)">{{ item.reference }} · {{ item.merchant_name }}</option></select>
        <button class="button button-secondary" :disabled="busy" @click="previewTransfer">Preview</button>
      </div>
      <div v-if="transferPreview" class="preview-result">
        <p>{{ transferPreview.eligible_count }} eligible · {{ transferPreview.excluded_count }} excluded · {{ transferPreview.environment }}</p>
        <div v-for="row in transferPreview.records" :key="row.declaration_id" class="preview-row">
          <span>{{ row.reference }} · {{ row.merchant }}</span><strong>{{ row.eligible ? "Ready" : row.issues.join(" ") }}</strong>
        </div>
        <button class="button button-primary" :disabled="busy || !transferPreview.eligible_count" @click="confirmTransfer">Confirm simulated transfer</button>
      </div>
    </div>
    <div class="panel-heading subheading"><div><h3>Recent transfer history</h3><p>Responses are stored locally in this demo database.</p></div></div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle" />
  </section>

  <section v-else-if="moduleKey === 'admin'" class="panel">
    <div class="panel-heading"><div><h2>Accounts</h2><p>Development account provisioning is separate from the public API.</p></div></div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle" />
    <div class="panel-heading subheading"><div><h2>Explainable risk rules</h2><p>Changes apply to new assessments; historical results retain their rule-set version.</p></div></div>
    <div class="rule-list">
      <div v-for="rule in extras.riskRules" :key="rule.id" class="rule-item">
        <div><strong>{{ rule.title }}</strong><p>{{ rule.description }}</p><small>+{{ rule.points }} points · rule version {{ rule.version }}</small></div>
        <button class="button button-small" @click="updateRule(rule)">{{ rule.enabled ? "Disable" : "Enable" }}</button>
      </div>
    </div>
  </section>

  <section v-else-if="moduleKey === 'risk'" class="panel">
    <div class="panel-heading">
      <div><h2>Assessment history</h2><p>Each result records its score, evidence, triggered rules, and data limitations.</p></div>
    </div>
    <div class="toolbar">
      <select v-model="selectedMerchant"><option value="">Select merchant to assess</option><option v-for="merchant in extras.merchants" :key="merchant.id" :value="String(merchant.id)">{{ merchant.business_name }} · {{ merchant.tin }}</option></select>
      <button class="button button-primary" :disabled="busy" @click="runRisk">Run assessment</button>
    </div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle" />
    <div v-if="list.length" class="assessment-notes">
      <strong>Decision-support only</strong>
      <p>Scores summarize configured indicators. They do not prove evasion and do not trigger enforcement automatically.</p>
    </div>
  </section>

  <section v-else-if="moduleKey === 'cases'" class="panel">
    <div class="toolbar"><input v-model="search" type="search" placeholder="Search case, merchant, or reason" @keydown.enter="load" /><button class="button button-secondary" @click="load">Search</button></div>
    <div v-if="showForm" class="form-panel">
      <h3>Create an investigation</h3>
      <form class="inline-form" @submit.prevent="createRecord">
        <label>Merchant<select v-model="form.merchant" required><option value="">Select merchant</option><option v-for="m in extras.merchants" :key="m.id" :value="String(m.id)">{{ m.business_name }} · {{ m.tin }}</option></select></label>
        <label>Source<input v-model="form.source" required placeholder="Reconciliation exception" /></label>
        <label>Reason<textarea v-model="form.reason" required rows="2" placeholder="Describe the review question"></textarea></label>
        <label>Priority<select v-model="form.priority"><option value="normal">Normal</option><option value="low">Low</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
        <label>Due date<input v-model="form.due_date" type="date" /></label>
        <button class="button button-primary" :disabled="busy">Create case</button>
      </form>
    </div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle">
      <template #actions="{ item }">
        <div class="row-actions">
          <button class="text-action" @click="addCaseNote(item)">Add note</button>
          <button v-if="['admin','supervisor'].includes(authUser?.role ?? '')" class="text-action" @click="assigningCase = item">Assign</button>
          <button v-if="['open','returned'].includes(item.status)" class="text-action" @click="caseTransition(item,'in_review')">Start review</button>
          <button v-if="item.status === 'in_review'" class="text-action" @click="caseTransition(item,'recommended')">Submit recommendation</button>
          <button v-if="['admin','supervisor'].includes(authUser?.role ?? '') && item.status === 'recommended'" class="text-action" @click="caseTransition(item,'approved')">Approve</button>
          <div v-if="assigningCase?.id === item.id" class="assign-inline">
            <select v-model="assignOfficerId"><option value="">Choose officer</option><option v-for="officer in extras.officers" :key="officer.id" :value="String(officer.id)">{{ officer.username }}</option></select>
            <button class="text-action" @click="saveCaseAssignment(item)">Save</button>
            <button class="text-action muted" @click="assigningCase = null">Cancel</button>
          </div>
        </div>
      </template>
    </DataTable>
  </section>

  <section v-else-if="moduleKey === 'social'" class="panel">
    <div class="toolbar">
      <input v-model="search" type="search" placeholder="Search profile or public business identifier" @keydown.enter="load" />
      <select v-model="platformFilter"><option value="">All platforms</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="x">X</option></select>
      <button class="button button-secondary" @click="load">Search</button>
    </div>
    <div class="review-link">
      <span>Link candidate to merchant:</span>
      <select v-model="reviewMerchantId"><option value="">Select merchant</option><option v-for="m in extras.merchants" :key="m.id" :value="String(m.id)">{{ m.business_name }} · {{ m.tin }}</option></select>
    </div>
    <div class="import-bar">
      <input type="file" accept=".csv,text/csv" @change="selectedFile = ($event.target as HTMLInputElement).files?.[0] ?? null" />
      <button class="button button-secondary" :disabled="busy || !selectedFile || !platformFilter" @click="importCsv">Import selected platform CSV</button>
      <a class="text-action" :href="`${API_BASE}/templates/${platformFilter || 'facebook'}-leads.csv`">Download sample template</a>
    </div>
    <div v-if="showForm" class="form-panel">
      <h3>Add a public business lead</h3>
      <form class="inline-form" @submit.prevent="createRecord">
        <label>Platform<select v-model="form.platform" required><option value="">Select platform</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="x">X</option></select></label>
        <label>Public profile name<input v-model="form.profile_name" required /></label>
        <label>Profile URL<input v-model="form.profile_url" type="url" /></label>
        <label>Public business identifier<input v-model="form.public_business_identifier" /></label>
        <label>Observation<textarea v-model="form.observation" rows="2" required></textarea></label>
        <button class="button button-primary" :disabled="busy">Save for review</button>
      </form>
      <p class="small-note">Only authorized public business information. No scraping or private communications.</p>
    </div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle">
      <template #actions="{ item }">
        <div class="row-actions">
          <button class="text-action" @click="reviewLead(item,'reviewed')">Mark reviewed</button>
          <button class="text-action" @click="reviewLead(item,'linked')">Link merchant</button>
          <button v-if="item.review_status === 'linked' && !item.linked_case" class="text-action" @click="createLeadCase(item)">Create case</button>
          <button class="text-action danger-text" @click="reviewLead(item,'rejected')">Reject</button>
        </div>
      </template>
    </DataTable>
  </section>

  <section v-else-if="moduleKey === 'transactions'" class="panel">
    <div class="toolbar">
      <input v-model="search" type="search" placeholder="Search reference or TIN" @keydown.enter="load" />
      <select v-model="sourceCode"><option value="">All sources</option><option v-for="source in extras.sources" :key="source.id" :value="source.code">{{ source.name }}</option></select>
      <button class="button button-secondary" @click="load">Search</button>
    </div>
    <div class="import-bar">
      <select v-model="sourceCode" aria-label="Import source"><option value="">Choose source for CSV import</option><option v-for="source in extras.sources" :key="source.id" :value="source.code">{{ source.name }}</option></select>
      <input type="file" accept=".csv,text/csv" @change="selectedFile = ($event.target as HTMLInputElement).files?.[0] ?? null" />
      <button class="button button-secondary" :disabled="busy || !selectedFile || !sourceCode" @click="importCsv">Import CSV</button>
    </div>
    <div class="import-bar">
      <a class="text-action" :href="`${API_BASE}/templates/transactions.csv`">Download transaction CSV template</a>
    </div>
    <div v-if="showForm" class="form-panel">
      <h3>Manual transaction entry</h3>
      <form class="inline-form" @submit.prevent="createRecord">
        <label>Source<select v-model="form.source" required><option value="">Select source</option><option v-for="source in extras.sources" :key="source.id" :value="String(source.id)">{{ source.name }}</option></select></label>
        <label>Merchant<select v-model="form.merchant"><option value="">Unlinked</option><option v-for="m in extras.merchants" :key="m.id" :value="String(m.id)">{{ m.business_name }} · {{ m.tin }}</option></select></label>
        <label>TIN<input v-model="form.tin" pattern="200076899[0-9]" maxlength="10" /></label>
        <label>Transaction reference<input v-model="form.reference" required /></label>
        <label>Date and time<input v-model="form.transaction_at" type="datetime-local" required /></label>
        <label>Amount<input v-model="form.amount" type="number" min="0" step="0.01" required /></label>
        <label>Currency<select v-model="form.currency"><option>USD</option><option>ZWL</option></select></label>
        <label>Type<input v-model="form.transaction_type" placeholder="payment" /></label>
        <label>Payment reference<input v-model="form.payment_reference" /></label>
        <button class="button button-primary" :disabled="busy">Save transaction</button>
      </form>
    </div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle" />
    <p class="small-note">References are masked where appropriate. Source connectors are disabled; imports carry file provenance.</p>
  </section>

  <section v-else-if="moduleKey === 'reconciliation'" class="panel">
    <div class="toolbar">
      <select v-model="platformFilter"><option value="">All outcomes</option><option value="amount_discrepancy">Amount discrepancy</option><option value="partially_matched">Partially matched</option><option value="unmatched_declaration">Unmatched declaration</option><option value="currency_discrepancy">Currency discrepancy</option><option value="potential_duplicate">Potential duplicate</option></select>
      <button class="button button-secondary" @click="load">Filter</button>
      <button class="button button-primary" :disabled="busy" @click="runReconciliation">Run reconciliation</button>
    </div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle">
      <template #actions="{ item }"><button v-if="item.status !== 'matched'" class="text-action" @click="resolveException(item)">Record resolution</button></template>
    </DataTable>
    <p class="small-note">A mismatch can reflect missing source coverage or timing. It is not proof of wrongdoing.</p>
  </section>

  <section v-else-if="moduleKey === 'identity'" class="panel">
    <div class="identity-note"><strong>Human decision required</strong><span>Name similarity alone never merges records. Review evidence and preserve source records.</span></div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle">
      <template #actions="{ item }">
        <div class="row-actions">
          <button class="text-action" @click="decideIdentity(item,'accepted')">Accept link</button>
          <button class="text-action" @click="decideIdentity(item,'deferred')">Defer</button>
          <button class="text-action danger-text" @click="decideIdentity(item,'rejected')">Reject</button>
        </div>
      </template>
    </DataTable>
  </section>

  <section v-else-if="moduleKey === 'merchants'" class="panel">
    <div class="toolbar"><input v-model="search" type="search" placeholder="Search name or TIN" @keydown.enter="load" /><button class="button button-secondary" @click="load">Search</button></div>
    <div v-if="showForm && canEditProfile" class="form-panel">
      <h3>Update business profile</h3>
      <form class="inline-form" @submit.prevent="saveProfile">
        <label>Legal name<input v-model="form.name" required /></label>
        <label>Business name<input v-model="form.business_name" required /></label>
        <label>Business type<input v-model="form.business_type" /></label>
        <label>Email<input v-model="form.email" type="email" /></label>
        <label>Phone<input v-model="form.phone" /></label>
        <label>City<input v-model="form.city" /></label>
        <label>Address<input v-model="form.address" /></label>
        <button class="button button-primary" :disabled="busy">Save profile</button>
      </form>
    </div>
    <div v-else-if="showForm" class="form-panel">
      <h3>Register merchant</h3>
      <form class="inline-form" @submit.prevent="createRecord">
        <label>TIN<input v-model="form.tin" pattern="200076899[0-9]" maxlength="10" required placeholder="2000768990" /></label>
        <label>Legal name<input v-model="form.name" required /></label>
        <label>Business name<input v-model="form.business_name" required /></label>
        <label>Business type<input v-model="form.business_type" /></label>
        <label>Email<input v-model="form.email" type="email" /></label>
        <label>Phone<input v-model="form.phone" /></label>
        <label>City<input v-model="form.city" /></label>
        <label>Address<input v-model="form.address" /></label>
        <button class="button button-primary" :disabled="busy">Save merchant</button>
      </form>
      <p class="small-note">The TIN pattern is a demonstration-only rule and must be verified before production use.</p>
    </div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle">
      <template #actions="{ item }"><button class="text-action" @click="selectedMerchant = String(item.id); checkTin()">Check TIN in TaRMS</button></template>
    </DataTable>
  </section>

  <section v-else-if="moduleKey === 'declarations'" class="panel">
    <div class="toolbar"><input v-model="search" type="search" placeholder="Search reference or merchant" @keydown.enter="load" /><button class="button button-secondary" @click="load">Search</button><button class="button button-secondary" @click="download('declarations')">Download CSV</button></div>
    <div v-if="showForm" class="form-panel">
      <h3>Declaration draft</h3>
      <form class="inline-form" @submit.prevent="createRecord">
        <label v-if="authUser?.role !== 'merchant'">Merchant<select v-model="form.merchant" required><option value="">Select merchant</option><option v-for="m in extras.merchants" :key="m.id" :value="String(m.id)">{{ m.business_name }} · {{ m.tin }}</option></select></label>
        <label>Period<input v-model="form.period" type="month" required /></label>
        <label>Currency<select v-model="form.currency"><option>USD</option><option>ZWL</option></select></label>
        <label>Declared revenue<input v-model="form.declared_revenue" type="number" min="0" step="0.01" required /></label>
        <label>Tax amount<input v-model="form.tax_amount" type="number" min="0" step="0.01" required /></label>
        <button class="button button-primary" :disabled="busy">Save draft</button>
      </form>
    </div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle">
      <template #actions="{ item }">
        <div class="row-actions">
          <button v-if="item.status === 'draft' && authUser?.role === 'merchant'" class="text-action" @click="submitDeclaration(item)">Submit</button>
          <button v-if="item.status === 'needs_info' && authUser?.role === 'merchant'" class="text-action" @click="respondToDeclaration(item)">Respond</button>
          <button v-if="item.status === 'submitted' && ['admin','supervisor','officer'].includes(authUser?.role ?? '')" class="text-action" @click="reviewDeclaration(item,'request_information')">Request info</button>
          <button v-if="item.status === 'submitted' && ['admin','supervisor'].includes(authUser?.role ?? '')" class="text-action" @click="reviewDeclaration(item,'approve')">Approve</button>
          <button v-if="item.status === 'submitted' && ['admin','supervisor'].includes(authUser?.role ?? '')" class="text-action danger-text" @click="reviewDeclaration(item,'return')">Return</button>
        </div>
      </template>
    </DataTable>
  </section>

  <section v-else-if="moduleKey === 'imports' || moduleKey === 'audit'" class="panel">
    <div class="panel-heading"><div><h2>{{ moduleKey === "imports" ? "Import batches" : "Recent recorded events" }}</h2><p>Data is loaded from the current application database.</p></div></div>
    <DataTable :items="list" :columns="columns" :display-value="displayValue" :field-title="fieldTitle" />
  </section>

  <div v-if="loading" class="loading-row"><span class="spinner"></span> Loading records…</div>
  <section v-if="showForm && moduleKey === 'admin'" class="modal-backdrop" @click.self="resetForm">
    <div class="modal-card">
      <button class="modal-close" @click="resetForm">×</button>
      <h2>Create user account</h2>
      <form class="stack-form" @submit.prevent="createRecord">
        <label>Username<input v-model="form.username" required minlength="3" /></label>
        <label>Email<input v-model="form.email" type="email" required /></label>
        <label>Role<select v-model="form.role" required><option value="">Select role</option><option value="admin">Administrator</option><option value="supervisor">Supervisor</option><option value="officer">Tax compliance officer</option><option value="merchant">Merchant</option></select></label>
        <label>Department<input v-model="form.department" /></label>
        <label>Temporary password<input v-model="form.password" type="password" minlength="12" required /></label>
        <button class="button button-primary" :disabled="busy">Create account</button>
      </form>
    </div>
  </section>
  <section v-else-if="showForm && moduleKey !== 'merchants' && moduleKey !== 'declarations' && moduleKey !== 'transactions' && moduleKey !== 'cases' && moduleKey !== 'social'" class="modal-backdrop" @click.self="resetForm">
    <div class="modal-card"><button class="modal-close" @click="resetForm">×</button><h2>New record</h2></div>
  </section>
</template>

<script lang="ts">
import { defineComponent, h } from "vue";

const DataTable = defineComponent({
  name: "DataTable",
  props: {
    items: { type: Array, default: () => [] },
    columns: { type: Array, default: () => [] },
    displayValue: { type: Function, required: true },
    fieldTitle: { type: Function, required: true },
  },
  setup(props, { slots }) {
    return () => h("div", { class: "table-wrap" }, [
      h("table", { class: "data-table" }, [
        h("thead", [h("tr", [
          ...((props.columns as string[]).map((column) => h("th", String(props.fieldTitle(column))))),
          h("th", "Actions"),
        ])]),
        h("tbody", [
          ...(props.items as any[]).map((item) =>
            h("tr", { key: item.id }, [
              ...((props.columns as string[]).map((column) =>
                h("td", { class: column === "status" || column === "band" || column === "reconciliation_status" ? "status-cell" : "" }, [
                  h("span", { class: `status-tag ${String(item[column] ?? "").toLowerCase()}` }, String(props.displayValue(item, column))),
                ]),
              )),
              h("td", { class: "actions-cell" }, slots.actions ? slots.actions({ item }) : "—"),
            ]),
          ),
        ]),
      ]),
      (props.items as any[]).length === 0 ? h("div", { class: "empty-state" }, "No matching records. Try changing the filters or add a new record.") : null,
    ]);
  },
});

export default defineComponent({ components: { DataTable } });
</script>
