<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../auth";

const auth = useAuthStore();
const router = useRouter();
const registering = ref(false);
const busy = ref(false);
const error = ref("");
const username = ref("");
const password = ref("");
const form = ref({
  username: "",
  email: "",
  password: "",
  name: "",
  business_name: "",
  tin: "",
  phone: "",
});

async function submitLogin() {
  busy.value = true;
  error.value = "";
  try {
    await auth.login(username.value.trim(), password.value);
    await router.replace("/");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Unable to sign in.";
  } finally {
    busy.value = false;
  }
}

async function submitRegistration() {
  busy.value = true;
  error.value = "";
  try {
    if (!/^200076899\d$/.test(form.value.tin)) {
      throw new Error("For this prototype, the TIN must be 10 digits and begin with 200076899.");
    }
    await auth.register({ ...form.value });
    await router.replace("/");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Unable to create the account.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-aside">
      <RouterLink to="/" class="brand brand-light">
        <span class="brand-mark">T</span>
        <span><strong>TMCIS</strong><small>INTELLIGENCE</small></span>
      </RouterLink>
      <div class="login-message">
        <div class="eyebrow">TAX MONITORING & COMPLIANCE</div>
        <h1>Clear records.<br /><em>Better decisions.</em></h1>
        <p>A prototype workspace for declarations, authorized data review, and human-led case workflows.</p>
      </div>
      <div class="aside-note">
        <span class="status-dot"></span>
        <span><strong>Simulation mode</strong><small>No live banking, social, or TaRMS service is connected.</small></span>
      </div>
      <div class="login-decoration">TMCIS <span>•</span> FICTIONAL DATA ONLY</div>
    </div>
    <div class="login-panel">
      <div class="login-form-wrap">
        <div class="form-kicker">{{ registering ? "MERCHANT PORTAL" : "SECURE WORKSPACE" }}</div>
        <h2>{{ registering ? "Create merchant account" : "Welcome back" }}</h2>
        <p class="muted">{{ registering ? "Register a business profile for the demonstration portal." : "Sign in to continue to your workspace." }}</p>
        <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
        <form v-if="!registering" @submit.prevent="submitLogin">
          <label>Username<input v-model="username" autocomplete="username" required placeholder="Enter your username" /></label>
          <label>Password<input v-model="password" type="password" autocomplete="current-password" required placeholder="Enter your password" /></label>
          <button class="button button-primary full-width" :disabled="busy">{{ busy ? "Signing in…" : "Sign in" }} <span>→</span></button>
        </form>
        <form v-else class="registration-form" @submit.prevent="submitRegistration">
          <label>Account username<input v-model="form.username" autocomplete="username" required minlength="3" /></label>
          <label>Email address<input v-model="form.email" type="email" autocomplete="email" required /></label>
          <label>Full name<input v-model="form.name" autocomplete="name" required /></label>
          <label>Business name<input v-model="form.business_name" required /></label>
          <label>Demonstration TIN<input v-model="form.tin" inputmode="numeric" pattern="200076899[0-9]" maxlength="10" required placeholder="2000768990" /></label>
          <label>Phone <span class="optional">OPTIONAL</span><input v-model="form.phone" autocomplete="tel" /></label>
          <label>Password<input v-model="form.password" type="password" autocomplete="new-password" minlength="12" required /></label>
          <button class="button button-primary full-width" :disabled="busy">{{ busy ? "Creating account…" : "Create account" }} <span>→</span></button>
        </form>
        <button class="text-button" @click="registering = !registering; error = ''">
          {{ registering ? "Already have an account? Sign in" : "Need a merchant account? Register" }}
        </button>
        <div class="login-footnote">By signing in, you acknowledge this is a fictional demonstration environment.</div>
      </div>
    </div>
  </div>
</template>
