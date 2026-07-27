<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue";
import type { Reference } from "./types/reference";
import { searchReferences } from "./api/references";
import SearchBar from "./components/SearchBar.vue";
import ReferenceList from "./components/ReferenceList.vue";
import ReferenceDetail from "./components/ReferenceDetail.vue";
import EmptyState from "./components/EmptyState.vue";
import LoadingState from "./components/LoadingState.vue";
import RegistrationPanel from "./components/RegistrationPanel.vue";
import ThemeSwitcher from "./components/ThemeSwitcher.vue";

const query = ref("");
const references = ref<Reference[]>([]);
const selectedReference = ref<Reference | null>(null);
const isLoading = ref(false);
const errorMessage = ref<string | null>(null);
const hasSearched = ref(false);
const mobileView = ref<"library" | "detail">("library");
const mobileBackButton = ref<HTMLButtonElement | null>(null);

onMounted(() => {
  void loadReferences("");
});

async function loadReferences(searchQuery: string) {
  isLoading.value = true;
  errorMessage.value = null;
  selectedReference.value = null;

  try {
    references.value = await searchReferences(searchQuery);
    selectedReference.value = references.value[0] ?? null;
  } catch (error) {
    console.error(error);
    errorMessage.value = "Failed to load references.";
    references.value = [];
  } finally {
    isLoading.value = false;
  }
}

async function handleSearch() {
  mobileView.value = "library";
  hasSearched.value = true;
  await loadReferences(query.value);
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

function handleReferenceRegistered(reference: Reference) {
  const existingIndex = references.value.findIndex((item) => item.id === reference.id);
  if (existingIndex >= 0) {
    references.value[existingIndex] = reference;
  } else {
    references.value = [reference, ...references.value];
  }

  selectedReference.value = reference;
  hasSearched.value = true;

  if (window.matchMedia("(max-width: 720px)").matches) {
    mobileView.value = "detail";
  }
}
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div class="app-shell app-header__inner">
        <div class="brand-mark" aria-hidden="true">
          <img src="/favicon.svg" alt="" width="34" height="34" />
        </div>
        <div class="brand-copy">
          <h1 class="brand-wordmark" aria-label="BibMgR">
            <span class="brand-wordmark__glyph" aria-hidden="true"></span>
          </h1>
          <p>Laboratory Bibliography Manager</p>
        </div>
        <ThemeSwitcher />
      </div>
    </header>

    <main class="app-shell app-main">
      <section
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
                :aria-label="`${references.length} ${references.length === 1 ? 'reference' : 'references'}`"
              >
                {{ references.length }}
              </span>
            </div>
            <RegistrationPanel @registered="handleReferenceRegistered" />
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
            <div class="state-icon" aria-hidden="true">!</div>
            <h2>References could not be loaded</h2>
            <p>{{ errorMessage }}</p>
            <button type="button" class="button-secondary" @click="handleSearch">
              Try again
            </button>
          </div>

          <EmptyState
            v-else-if="references.length === 0 && !hasSearched"
            title="No test references loaded"
            message="The local test dataset is empty. Add sample entries or connect the backend database to show references."
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
        </aside>

        <section class="right-pane" aria-label="Reference details">
          <button
            ref="mobileBackButton"
            type="button"
            class="mobile-back"
            @click="showLibrary"
          >
            <svg aria-hidden="true" viewBox="0 0 16 16" fill="none">
              <path d="m10 3-5 5 5 5" />
            </svg>
            References
          </button>
          <ReferenceDetail :reference="selectedReference" />
        </section>
      </section>
    </main>
  </div>
</template>
