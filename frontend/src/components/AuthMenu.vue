<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from "vue";
import {
  logout,
  startEmailLogin,
  verifyEmailLogin,
} from "../api/auth";
import type { AuthenticationSession } from "../types/auth";

const props = defineProps<{
  session: AuthenticationSession;
}>();

const emit = defineEmits<{
  sessionChanged: [session: AuthenticationSession];
}>();

const isOpen = ref(false);
const isSignOutOpen = ref(false);
const step = ref<"email" | "code">("email");
const email = ref("");
const code = ref("");
const isSubmitting = ref(false);
const errorMessage = ref<string | null>(null);
const statusMessage = ref<string | null>(null);
const dialog = ref<HTMLElement | null>(null);
const signOutDialog = ref<HTMLElement | null>(null);
const loginButton = ref<HTMLButtonElement | null>(null);
const signOutButton = ref<HTMLButtonElement | null>(null);

onBeforeUnmount(() => {
  document.body.classList.remove("auth-open");
});

async function openLogin() {
  if (props.session.authenticated) return;
  isOpen.value = true;
  errorMessage.value = null;
  document.body.classList.add("auth-open");
  await nextTick();
  dialog.value?.focus({ preventScroll: true });
}

async function closeLogin() {
  isOpen.value = false;
  document.body.classList.remove("auth-open");
  await nextTick();
  loginButton.value?.focus({ preventScroll: true });
}

async function requestCode() {
  if (!email.value.trim() || isSubmitting.value) return;
  isSubmitting.value = true;
  errorMessage.value = null;
  statusMessage.value = null;

  try {
    const result = await startEmailLogin(email.value.trim());
    step.value = "code";
    statusMessage.value = result.message;
    await nextTick();
    document.querySelector<HTMLInputElement>("#login-code")?.focus();
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "Could not send a login code.";
  } finally {
    isSubmitting.value = false;
  }
}

async function verifyCode() {
  if (!/^[0-9]{8}$/.test(code.value) || isSubmitting.value) return;
  isSubmitting.value = true;
  errorMessage.value = null;

  try {
    const session = await verifyEmailLogin(
      email.value.trim(),
      code.value,
    );
    emit("sessionChanged", session);
    code.value = "";
    statusMessage.value = null;
    await closeLogin();
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "Could not verify the login code.";
  } finally {
    isSubmitting.value = false;
  }
}

async function requestSignOut() {
  if (isSubmitting.value) return;
  isSignOutOpen.value = true;
  errorMessage.value = null;
  document.body.classList.add("auth-open");
  await nextTick();
  signOutDialog.value?.focus({ preventScroll: true });
}

async function cancelSignOut() {
  if (isSubmitting.value) return;
  isSignOutOpen.value = false;
  errorMessage.value = null;
  document.body.classList.remove("auth-open");
  await nextTick();
  signOutButton.value?.focus({ preventScroll: true });
}

async function confirmSignOut() {
  if (isSubmitting.value) return;
  isSubmitting.value = true;
  errorMessage.value = null;

  try {
    await logout();
    emit("sessionChanged", {
      schema_version: "1",
      authenticated: false,
    });
    step.value = "email";
    email.value = "";
    code.value = "";
    isSignOutOpen.value = false;
    document.body.classList.remove("auth-open");
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "Could not log out.";
  } finally {
    isSubmitting.value = false;
  }
}

function returnToEmail() {
  step.value = "email";
  code.value = "";
  errorMessage.value = null;
  statusMessage.value = null;
}

function onDialogKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeLogin();
    return;
  }
  trapDialogFocus(event, dialog.value);
}

function onSignOutDialogKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    void cancelSignOut();
    return;
  }
  trapDialogFocus(event, signOutDialog.value);
}

function trapDialogFocus(event: KeyboardEvent, root: HTMLElement | null) {
  if (event.key !== "Tab" || !root) return;
  const focusable = Array.from(
    root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.getClientRects().length > 0);
  const first = focusable[0];
  const last = focusable.at(-1);
  if (!first || !last) return;
  if (
    event.shiftKey &&
    (document.activeElement === first || document.activeElement === root)
  ) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

defineExpose({ openLogin });
</script>

<template>
  <div class="auth-menu">
    <template v-if="session.authenticated && session.user">
      <span class="auth-identity" :title="session.user.email">
        {{ session.user.email }}
      </span>
      <button
        ref="signOutButton"
        type="button"
        class="auth-button auth-button--secondary"
        :disabled="isSubmitting"
        aria-haspopup="dialog"
        :aria-expanded="isSignOutOpen"
        @click="requestSignOut"
      >
        Sign out
      </button>
    </template>
    <button
      v-else
      ref="loginButton"
      type="button"
      class="auth-button"
      aria-haspopup="dialog"
      :aria-expanded="isOpen"
      @click="openLogin"
    >
      Log in
    </button>

    <Teleport v-if="isOpen" to="body">
      <div
        class="auth-backdrop"
        @click.self="closeLogin"
      >
        <section
          ref="dialog"
          class="auth-sheet"
          role="dialog"
          aria-modal="true"
          aria-labelledby="auth-heading"
          tabindex="-1"
          @keydown="onDialogKeydown"
        >
          <header class="auth-sheet__header">
            <div>
              <p class="auth-eyebrow">Laboratory account</p>
              <h2 id="auth-heading">Log in to BibMgR</h2>
              <p>
                A laboratory account is required to access the reference
                library and BibTeX tools.
              </p>
            </div>
            <button
              type="button"
              class="registration-close"
              aria-label="Close login"
              @click="closeLogin"
            >
              <svg aria-hidden="true" viewBox="0 0 18 18" fill="none">
                <path d="m5 5 8 8M13 5l-8 8" />
              </svg>
            </button>
          </header>

          <form
            v-if="step === 'email'"
            class="auth-form"
            @submit.prevent="requestCode"
          >
            <label class="field-label" for="login-email">
              Laboratory email
              <span>
                Use your @ai.cs.ehime-u.ac.jp address or an individually
                approved address.
              </span>
            </label>
            <input
              id="login-email"
              v-model="email"
              class="auth-input"
              type="email"
              inputmode="email"
              autocomplete="email"
              placeholder="name@ai.cs.ehime-u.ac.jp"
              required
            />
            <p v-if="errorMessage" class="registration-error" role="alert">
              {{ errorMessage }}
            </p>
            <button
              type="submit"
              class="button-primary auth-submit"
              :disabled="!email.trim() || isSubmitting"
              :aria-busy="isSubmitting"
            >
              {{ isSubmitting ? "Sending…" : "Send login code" }}
            </button>
          </form>

          <form
            v-else
            class="auth-form"
            @submit.prevent="verifyCode"
          >
            <button
              type="button"
              class="auth-back-button"
              @click="returnToEmail"
            >
              Change email
            </button>
            <label class="field-label" for="login-code">
              8-digit login code
              <span>Sent to {{ email.trim() }}. It expires in 10 minutes.</span>
            </label>
            <input
              id="login-code"
              v-model="code"
              class="auth-input auth-code-input"
              type="text"
              inputmode="numeric"
              autocomplete="one-time-code"
              pattern="[0-9]{8}"
              maxlength="8"
              placeholder="00000000"
              required
            />
            <p
              v-if="statusMessage && !errorMessage"
              class="registration-message"
              role="status"
            >
              {{ statusMessage }}
            </p>
            <p v-if="errorMessage" class="registration-error" role="alert">
              {{ errorMessage }}
            </p>
            <button
              type="submit"
              class="button-primary auth-submit"
              :disabled="code.length !== 8 || isSubmitting"
              :aria-busy="isSubmitting"
            >
              {{ isSubmitting ? "Verifying…" : "Log in" }}
            </button>
          </form>
        </section>
      </div>
    </Teleport>

    <Teleport v-if="isSignOutOpen" to="body">
      <div
        class="auth-backdrop"
        @click.self="cancelSignOut"
      >
        <section
          ref="signOutDialog"
          class="auth-sheet confirmation-sheet"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="sign-out-heading"
          aria-describedby="sign-out-description"
          tabindex="-1"
          @keydown="onSignOutDialogKeydown"
        >
          <header class="auth-sheet__header">
            <div>
              <p class="auth-eyebrow">Laboratory account</p>
              <h2 id="sign-out-heading">Sign out?</h2>
              <p id="sign-out-description">
                You will need a new email login code before accessing BibMgR
                again.
              </p>
            </div>
          </header>
          <p
            v-if="errorMessage"
            class="registration-error confirmation-error"
            role="alert"
          >
            {{ errorMessage }}
          </p>
          <div class="confirmation-actions">
            <button
              type="button"
              class="button-secondary"
              :disabled="isSubmitting"
              @click="cancelSignOut"
            >
              Cancel
            </button>
            <button
              type="button"
              class="button-primary"
              :disabled="isSubmitting"
              :aria-busy="isSubmitting"
              @click="confirmSignOut"
            >
              {{ isSubmitting ? "Signing out…" : "Sign out" }}
            </button>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>
