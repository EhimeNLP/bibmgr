<script setup lang="ts">
import { onMounted, ref } from "vue";
import type { Reference } from "./types/reference";
import { searchReferences } from "./api/references";
import SearchBar from "./components/SearchBar.vue";
import ReferenceList from "./components/ReferenceList.vue";
import ReferenceDetail from "./components/ReferenceDetail.vue";
import EmptyState from "./components/EmptyState.vue";
import LoadingState from "./components/LoadingState.vue";
import RegistrationPanel from "./components/RegistrationPanel.vue";

const query = ref("");
const references = ref<Reference[]>([]);
const selectedReference = ref<Reference | null>(null);
const isLoading = ref(false);
const errorMessage = ref<string | null>(null);
const hasSearched = ref(false);

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
  hasSearched.value = true;
  await loadReferences(query.value);
}

function selectReference(reference: Reference) {
  selectedReference.value = reference;
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
}
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div>
        <h1>BibMgr</h1>
        <p>Laboratory Bibliography Manager</p>
      </div>
    </header>

    <main class="app-main">
      <section class="search-section">
        <SearchBar
          v-model="query"
          :disabled="isLoading"
          @search="handleSearch"
        />
      </section>

      <RegistrationPanel @registered="handleReferenceRegistered" />

      <section class="content-layout">
        <aside class="left-pane">
          <div class="pane-header">
            <h2>References</h2>
          </div>

          <LoadingState v-if="isLoading" />

          <div v-else-if="errorMessage" class="error-state">
            {{ errorMessage }}
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
            @select="selectReference"
          />
        </aside>

        <section class="right-pane">
          <ReferenceDetail :reference="selectedReference" />
        </section>
      </section>
    </main>
  </div>
</template>
