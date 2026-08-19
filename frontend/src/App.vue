<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import {
  AUTHENTICATION_REQUIRED_EVENT,
  clearRememberedAuthentication,
  getAuthenticationSession,
} from "./api/auth";
import type {
  Reference,
  ReferenceSearchFilters,
} from "./types/reference";
import type { AuthenticationSession } from "./types/auth";
import { searchReferencePage } from "./api/references";
import SearchBar from "./components/SearchBar.vue";
import ReferenceList from "./components/ReferenceList.vue";
import ReferenceDetail from "./components/ReferenceDetail.vue";
import EmptyState from "./components/EmptyState.vue";
import LoadingState from "./components/LoadingState.vue";
import RegistrationPanel from "./components/RegistrationPanel.vue";
import ThemeSwitcher from "./components/ThemeSwitcher.vue";
import AuthMenu from "./components/AuthMenu.vue";
import HistoryPanel from "./components/HistoryPanel.vue";
import SettingsPanel from "./components/SettingsPanel.vue";
import AppIcon from "./components/AppIcon.vue";

const query = ref("");
const references = ref<Reference[]>([]);
const selectedReference = ref<Reference | null>(null);
const isLoading = ref(false);
const errorMessage = ref<string | null>(null);
const hasSearched = ref(false);
const totalReferences = ref(0);
const pageLimit = 25;
const pageOffset = ref(0);
const activeFilters = ref<ReferenceSearchFilters>({
  query: "",
  sort: "updated_desc",
});
const mobileView = ref<"library" | "detail">("library");
const mobileBackButton = ref<HTMLButtonElement | null>(null);
const authMenu = ref<InstanceType<typeof AuthMenu> | null>(null);
const isAuthenticationLoading = ref(true);
const authenticationSession = ref<AuthenticationSession>({
  schema_version: "1",
  authenticated: false,
});
const configurationGeneration = ref(0);
let referenceLoadGeneration = 0;
const pageNumber = computed(() =>
  Math.floor(pageOffset.value / pageLimit) + 1
);
const pageCount = computed(() =>
  Math.max(1, Math.ceil(totalReferences.value / pageLimit))
);
const faviconUrl = `${import.meta.env.BASE_URL}favicon.svg`;

onMounted(() => {
  window.addEventListener(
    AUTHENTICATION_REQUIRED_EVENT,
    handleAuthenticationRequired,
  );
  void loadAuthenticationSession();
});

onBeforeUnmount(() => {
  window.removeEventListener(
    AUTHENTICATION_REQUIRED_EVENT,
    handleAuthenticationRequired,
  );
});

async function loadAuthenticationSession() {
  isAuthenticationLoading.value = true;
  try {
    authenticationSession.value = await getAuthenticationSession();
    if (authenticationSession.value.authenticated) {
      await loadReferences(activeFilters.value, 0);
    } else {
      resetProtectedWorkspace();
    }
  } catch (error) {
    console.error(error);
    authenticationSession.value = {
      schema_version: "1",
      authenticated: false,
    };
    resetProtectedWorkspace();
  } finally {
    isAuthenticationLoading.value = false;
  }
}

function handleAuthenticationChanged(session: AuthenticationSession) {
  authenticationSession.value = session;
  if (session.authenticated) {
    void loadReferences(activeFilters.value, 0);
  } else {
    clearRememberedAuthentication();
    resetProtectedWorkspace();
  }
}

function requestLogin() {
  void authMenu.value?.openLogin();
}

function handleAuthenticationRequired() {
  authenticationSession.value = {
    schema_version: "1",
    authenticated: false,
  };
  resetProtectedWorkspace();
  void authMenu.value?.openLogin();
}

async function loadReferences(
  filters: ReferenceSearchFilters,
  offset: number,
) {
  if (!authenticationSession.value.authenticated) return;
  const generation = ++referenceLoadGeneration;
  isLoading.value = true;
  errorMessage.value = null;
  selectedReference.value = null;

  try {
    const page = await searchReferencePage(filters, {
      limit: pageLimit,
      offset,
    });
    if (
      generation !== referenceLoadGeneration ||
      !authenticationSession.value.authenticated
    ) {
      return;
    }
    references.value = page.items;
    totalReferences.value = page.total;
    pageOffset.value = page.offset;
    selectedReference.value = references.value[0] ?? null;
  } catch (error) {
    if (
      generation !== referenceLoadGeneration ||
      !authenticationSession.value.authenticated
    ) {
      return;
    }
    console.error(error);
    errorMessage.value = "Failed to load references.";
    references.value = [];
    totalReferences.value = 0;
  } finally {
    if (generation === referenceLoadGeneration) {
      isLoading.value = false;
    }
  }
}

function resetProtectedWorkspace() {
  referenceLoadGeneration += 1;
  query.value = "";
  references.value = [];
  selectedReference.value = null;
  isLoading.value = false;
  errorMessage.value = null;
  hasSearched.value = false;
  totalReferences.value = 0;
  pageOffset.value = 0;
  activeFilters.value = {
    query: "",
    sort: "updated_desc",
  };
  mobileView.value = "library";
}

async function handleSearch(filters?: ReferenceSearchFilters) {
  mobileView.value = "library";
  hasSearched.value = true;
  activeFilters.value = filters ?? activeFilters.value;
  await loadReferences(activeFilters.value, 0);
}

async function selectReference(reference: Reference, event?: MouseEvent) {
  selectedReference.value = reference;

  if (!window.matchMedia("(max-width: 720px)").matches) return;

  mobileView.value = "detail";
  if (event?.detail !== 0) return;

  await nextTick();
  mobileBackButton.value?.focus({ preventScroll: true });
}

async function showLibrary(event?: MouseEvent) {
  mobileView.value = "library";
  if (event?.detail !== 0) return;

  await nextTick();
  document.querySelector<HTMLButtonElement>(".reference-card.selected")?.focus({
    preventScroll: true,
  });
}

async function refreshAfterReferenceWrite(reference: Reference) {
  await loadReferences(activeFilters.value, 0);
  selectedReference.value =
    references.value.find((item) => item.id === reference.id) ?? reference;
  hasSearched.value = true;

  if (window.matchMedia("(max-width: 720px)").matches) {
    mobileView.value = "detail";
  }
}

async function handleReferencesRegistered(registered: Reference[]) {
  const firstRegistered = registered[0];
  if (firstRegistered) await refreshAfterReferenceWrite(firstRegistered);
}

async function handleReferenceUpdated(reference: Reference) {
  await refreshAfterReferenceWrite(reference);
}

function handleReferenceRestored(reference: Reference) {
  void refreshAfterReferenceWrite(reference);
}

function handleConfigurationChanged() {
  configurationGeneration.value += 1;
}

async function handleReferenceDeleted() {
  const nextOffset =
    references.value.length === 1 && pageOffset.value > 0
      ? Math.max(0, pageOffset.value - pageLimit)
      : pageOffset.value;
  await loadReferences(activeFilters.value, nextOffset);
  hasSearched.value = true;

  if (
    window.matchMedia("(max-width: 720px)").matches &&
    !selectedReference.value
  ) {
    mobileView.value = "library";
  }
}

async function changePage(direction: -1 | 1) {
  const nextOffset = pageOffset.value + direction * pageLimit;
  if (nextOffset < 0 || nextOffset >= totalReferences.value) return;
  await loadReferences(activeFilters.value, nextOffset);
}
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div class="app-shell app-header__inner">
        <div class="brand-mark" aria-hidden="true">
          <img :src="faviconUrl" alt="" width="44" height="44" />
        </div>
        <div class="brand-copy">
          <h1 class="brand-wordmark" aria-label="BibMgR">
            <span class="brand-wordmark__glyph" aria-hidden="true"></span>
          </h1>
          <p>BibTeX Reference Manager</p>
        </div>
        <ThemeSwitcher />
        <SettingsPanel
          :authenticated="authenticationSession.authenticated"
          @changed="handleConfigurationChanged"
          @login-required="requestLogin"
        />
        <AuthMenu
          ref="authMenu"
          :session="authenticationSession"
          @session-changed="handleAuthenticationChanged"
        />
      </div>
    </header>

    <main class="app-shell app-main">
      <section
        v-if="isAuthenticationLoading"
        class="access-state"
        role="status"
        aria-live="polite"
      >
        <div class="state-icon" aria-hidden="true">
          <AppIcon name="clock" />
        </div>
        <h2>Checking your session…</h2>
        <p>BibMgR will open after your account is verified.</p>
      </section>

      <section
        v-else-if="!authenticationSession.authenticated"
        class="access-state"
        aria-labelledby="access-heading"
      >
        <div class="state-icon" aria-hidden="true">
          <AppIcon name="lock" />
        </div>
        <h2 id="access-heading">Log in to access BibMgR</h2>
        <p>
          Reference search, BibTeX tools, exports, and library changes require
          an account.
        </p>
        <button type="button" class="button-primary" @click="requestLogin">
          Log in to continue
        </button>
      </section>

      <section
        v-else
        class="content-layout"
        :class="{ 'show-detail': mobileView === 'detail' }"
        aria-label="Bibliography workspace"
      >
        <aside class="left-pane" :aria-busy="isLoading" aria-labelledby="references-heading">
          <div class="pane-header">
            <div class="pane-heading-row">
              <h2 id="references-heading">References</h2>
              <span
                v-if="!isLoading"
                class="count-badge"
                aria-live="polite"
                :aria-label="`${totalReferences} ${totalReferences === 1 ? 'reference' : 'references'}`"
              >
                {{ totalReferences }}
              </span>
            </div>
            <div class="pane-actions">
              <HistoryPanel
                :authenticated="authenticationSession.authenticated"
                @restored="handleReferenceRestored"
                @login-required="requestLogin"
              />
              <RegistrationPanel
                :key="`registration-${configurationGeneration}`"
                :authenticated="authenticationSession.authenticated"
                @registered="handleReferencesRegistered"
                @login-required="requestLogin"
              />
            </div>
          </div>

          <div class="sidebar-search">
            <SearchBar
              v-model="query"
              :disabled="isLoading"
              :loading="isLoading"
              @search="handleSearch"
            />
          </div>

          <LoadingState v-if="isLoading" />

          <div v-else-if="errorMessage" class="error-state" role="alert">
            <div class="state-icon" aria-hidden="true">
              <AppIcon name="exclamation-triangle" />
            </div>
            <h2>References could not be loaded</h2>
            <p>{{ errorMessage }}</p>
            <button type="button" class="button-secondary" @click="handleSearch()">
              Try again
            </button>
          </div>

          <EmptyState
            v-else-if="references.length === 0 && !hasSearched"
            title="No references found"
            message="The database is empty. Add a reference to start the library."
          />

          <EmptyState
            v-else-if="references.length === 0 && hasSearched"
            title="No matching references found"
            message="Try another keyword or check whether references have been registered."
          />

          <ReferenceList
            v-else
            :references="references"
            :selected-reference-id="selectedReference?.id"
            aria-labelledby="references-heading"
            @select="selectReference"
          />
          <nav
            v-if="!isLoading && totalReferences > pageLimit"
            class="pagination"
            aria-label="Reference pages"
          >
            <button
              type="button"
              class="button-secondary"
              :disabled="pageOffset === 0"
              @click="changePage(-1)"
            >
              Previous
            </button>
            <span>Page {{ pageNumber }} of {{ pageCount }}</span>
            <button
              type="button"
              class="button-secondary"
              :disabled="pageOffset + pageLimit >= totalReferences"
              @click="changePage(1)"
            >
              Next
            </button>
          </nav>
        </aside>

        <section class="right-pane" aria-label="Reference details">
          <button
            ref="mobileBackButton"
            type="button"
            class="mobile-back"
            @click="showLibrary"
          >
            <AppIcon name="chevron-left" />
            References
          </button>
          <ReferenceDetail
            :key="`detail-${configurationGeneration}`"
            :reference="selectedReference"
            :authenticated="authenticationSession.authenticated"
            @updated="handleReferenceUpdated"
            @deleted="handleReferenceDeleted"
            @login-required="requestLogin"
          />
        </section>
      </section>
    </main>
  </div>
</template>
