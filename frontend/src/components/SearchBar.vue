<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
} from "vue";
import type {
  ReferenceSearchFilters,
  ReferenceSort,
} from "../types/reference";

const props = defineProps<{
  modelValue: string;
  disabled?: boolean;
  loading?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
  search: [filters: ReferenceSearchFilters];
}>();

type AdvancedFilterKey =
  | "year"
  | "author"
  | "venue"
  | "identifier"
  | "entryType"
  | "createdBy"
  | "updatedFrom"
  | "updatedTo"
  | "sort";

type FilterToken = {
  key: AdvancedFilterKey;
  label: string;
};

type AdvancedFilters = {
  year: string | number;
  author: string;
  venue: string;
  identifier: string;
  entryType: string;
  createdBy: string;
  updatedFrom: string;
  updatedTo: string;
  sort: ReferenceSort;
};

const defaultSort: ReferenceSort = "updated_desc";
const root = ref<HTMLFormElement | null>(null);
const filterButton = ref<HTMLButtonElement | null>(null);
const filterPanel = ref<HTMLElement | null>(null);
const filtersOpen = ref(false);
const advanced = reactive<AdvancedFilters>(initialAdvancedFilters());
const applied = reactive<AdvancedFilters>(initialAdvancedFilters());

const sortLabels: Record<ReferenceSort, string> = {
  updated_desc: "Recently Updated",
  updated_asc: "Oldest Update",
  year_desc: "Newest Publication",
  year_asc: "Oldest Publication",
  title_asc: "Title",
};

const activeTokens = computed<FilterToken[]>(() => filterTokens(applied));
const draftTokens = computed<FilterToken[]>(() => filterTokens(advanced));

function initialAdvancedFilters(): AdvancedFilters {
  return {
    year: "",
    author: "",
    venue: "",
    identifier: "",
    entryType: "",
    createdBy: "",
    updatedFrom: "",
    updatedTo: "",
    sort: defaultSort,
  };
}

function filterTokens(filters: AdvancedFilters): FilterToken[] {
  const tokens: FilterToken[] = [];
  addToken(tokens, "year", "Year", filters.year);
  addToken(tokens, "author", "Author", filters.author);
  addToken(tokens, "venue", "Venue", filters.venue);
  addToken(tokens, "identifier", "Identifier", filters.identifier);
  addToken(tokens, "entryType", "Type", filters.entryType);
  addToken(tokens, "createdBy", "Created by", filters.createdBy);
  addToken(tokens, "updatedFrom", "Updated after", filters.updatedFrom);
  addToken(tokens, "updatedTo", "Updated before", filters.updatedTo);
  if (filters.sort !== defaultSort) {
    tokens.push({ key: "sort", label: sortLabels[filters.sort] });
  }
  return tokens;
}

const filterButtonLabel = computed(() => {
  const count = activeTokens.value.length;
  if (count === 0) return "Show search filters";
  return `Show search filters, ${count} active`;
});

onMounted(() => {
  document.addEventListener("pointerdown", closeWhenClickingOutside);
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", closeWhenClickingOutside);
});

function addToken(
  tokens: FilterToken[],
  key: AdvancedFilterKey,
  name: string,
  value: string | number,
) {
  const normalized = String(value).trim();
  if (normalized) tokens.push({ key, label: `${name}: ${normalized}` });
}

function buildFilters(filters: AdvancedFilters): ReferenceSearchFilters {
  const parsedYear = Number.parseInt(String(filters.year), 10);
  return {
    query: props.modelValue,
    year: Number.isInteger(parsedYear) ? parsedYear : undefined,
    author: filters.author.trim(),
    venue: filters.venue.trim(),
    identifier: filters.identifier.trim(),
    entryType: filters.entryType.trim(),
    createdBy: filters.createdBy.trim(),
    updatedFrom: filters.updatedFrom
      ? new Date(`${filters.updatedFrom}T00:00:00`).toISOString()
      : undefined,
    updatedTo: filters.updatedTo
      ? new Date(`${filters.updatedTo}T23:59:59.999`).toISOString()
      : undefined,
    sort: filters.sort,
  };
}

function onSubmit() {
  Object.assign(applied, advanced);
  filtersOpen.value = false;
  emit("search", buildFilters(applied));
}

function toggleFilters() {
  if (filtersOpen.value) {
    closeFilters();
    return;
  }

  filtersOpen.value = true;
  Object.assign(advanced, applied);
  void nextTick(() => {
    filterPanel.value?.querySelector<HTMLElement>("input, select")?.focus({
      preventScroll: true,
    });
  });
}

function closeFilters({ restoreFocus = false } = {}) {
  if (!filtersOpen.value) return;
  filtersOpen.value = false;
  Object.assign(advanced, applied);
  if (restoreFocus) {
    void nextTick(() => filterButton.value?.focus({ preventScroll: true }));
  }
}

function closeWhenClickingOutside(event: PointerEvent) {
  if (!filtersOpen.value || !(event.target instanceof Node)) return;
  if (!root.value?.contains(event.target)) closeFilters();
}

function clearFilter(key: AdvancedFilterKey) {
  resetFilter(applied, key);
  resetFilter(advanced, key);
  emit("search", buildFilters(applied));
}

function resetFilter(filters: AdvancedFilters, key: AdvancedFilterKey) {
  switch (key) {
    case "year":
      filters.year = "";
      break;
    case "author":
      filters.author = "";
      break;
    case "venue":
      filters.venue = "";
      break;
    case "identifier":
      filters.identifier = "";
      break;
    case "entryType":
      filters.entryType = "";
      break;
    case "createdBy":
      filters.createdBy = "";
      break;
    case "updatedFrom":
      filters.updatedFrom = "";
      break;
    case "updatedTo":
      filters.updatedTo = "";
      break;
    case "sort":
      filters.sort = defaultSort;
      break;
  }
}

function clearAllFilters() {
  Object.assign(advanced, initialAdvancedFilters());
  Object.assign(applied, initialAdvancedFilters());
  emit("search", buildFilters(applied));
}
</script>

<template>
  <form
    ref="root"
    class="search-bar"
    role="search"
    :aria-busy="props.loading"
    @submit.prevent="onSubmit"
    @keydown.esc="closeFilters({ restoreFocus: true })"
  >
    <div class="search-bar__controls">
      <label class="sr-only" for="reference-search">Search references</label>
      <div class="search-input">
        <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
          <circle cx="8.75" cy="8.75" r="5.75" />
          <path d="m13 13 4 4" />
        </svg>
        <input
          id="reference-search"
          :value="props.modelValue"
          :disabled="props.disabled"
          type="search"
          placeholder="Title, author, DOI, or key"
          autocomplete="off"
          @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <button
        type="submit"
        class="button-primary search-submit"
        :disabled="props.disabled"
        :aria-busy="props.loading"
        :aria-label="props.loading ? 'Searching references' : 'Search references'"
      >
        <span v-if="props.loading" class="button-spinner" aria-hidden="true" />
        <svg v-else aria-hidden="true" viewBox="0 0 20 20" fill="none">
          <circle cx="8.75" cy="8.75" r="5.75" />
          <path d="m13 13 4 4" />
        </svg>
        <span>{{ props.loading ? "Searching…" : "Search" }}</span>
      </button>
      <button
        ref="filterButton"
        type="button"
        class="search-filter-trigger"
        :class="{ active: filtersOpen || activeTokens.length > 0 }"
        :disabled="props.disabled"
        :aria-expanded="filtersOpen"
        aria-controls="reference-search-filters"
        :aria-label="filterButtonLabel"
        title="Filters"
        @click="toggleFilters"
      >
        <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
          <path d="M3 5h14M5.5 10h9M8 15h4" />
        </svg>
        <span
          v-if="activeTokens.length > 0"
          class="search-filter-trigger__count"
          aria-hidden="true"
        >
          {{ activeTokens.length }}
        </span>
      </button>
    </div>

    <div
      v-if="activeTokens.length > 0"
      class="search-tokens"
      aria-label="Active search filters"
    >
      <button
        v-for="token in activeTokens"
        :key="token.key"
        type="button"
        class="search-token"
        :disabled="props.disabled"
        :aria-label="`Remove ${token.label} filter`"
        @click="clearFilter(token.key)"
      >
        <span>{{ token.label }}</span>
        <svg aria-hidden="true" viewBox="0 0 12 12">
          <path d="m3.25 3.25 5.5 5.5m0-5.5-5.5 5.5" />
        </svg>
      </button>
    </div>

    <section
      v-if="filtersOpen"
      id="reference-search-filters"
      ref="filterPanel"
      class="search-filter-panel"
      aria-labelledby="reference-search-filters-title"
    >
      <div class="search-filter-panel__header">
        <div>
          <h3 id="reference-search-filters-title">Filters</h3>
          <p>Narrow the reference library.</p>
        </div>
        <button
          type="button"
          class="search-filter-panel__close"
          aria-label="Close filters"
          @click="closeFilters({ restoreFocus: true })"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20">
            <path d="m6 6 8 8m0-8-8 8" />
          </svg>
        </button>
      </div>

      <div class="search-filter-panel__body">
        <fieldset class="search-filter-group">
          <legend>Publication</legend>
          <div class="search-filter-grid">
            <label class="search-filter-field">
              <span>Year</span>
              <input
                v-model="advanced.year"
                type="number"
                min="1"
                max="9999"
                inputmode="numeric"
                placeholder="Any year"
              />
            </label>
            <label class="search-filter-field">
              <span>Entry type</span>
              <input
                v-model="advanced.entryType"
                type="search"
                placeholder="Any type"
              />
            </label>
            <label class="search-filter-field search-filter-field--wide">
              <span>Author</span>
              <input
                v-model="advanced.author"
                type="search"
                placeholder="Any author"
              />
            </label>
            <label class="search-filter-field search-filter-field--wide">
              <span>Venue</span>
              <input
                v-model="advanced.venue"
                type="search"
                placeholder="Journal or conference"
              />
            </label>
            <label class="search-filter-field search-filter-field--wide">
              <span>DOI or identifier</span>
              <input
                v-model="advanced.identifier"
                type="search"
                placeholder="DOI, arXiv ID, or key"
              />
            </label>
          </div>
        </fieldset>

        <fieldset class="search-filter-group">
          <legend>Library activity</legend>
          <div class="search-filter-grid">
            <label class="search-filter-field search-filter-field--wide">
              <span>Created by</span>
              <input
                v-model="advanced.createdBy"
                type="search"
                placeholder="Complete email address"
              />
            </label>
            <label class="search-filter-field">
              <span>Updated after</span>
              <input v-model="advanced.updatedFrom" type="date" />
            </label>
            <label class="search-filter-field">
              <span>Updated before</span>
              <input v-model="advanced.updatedTo" type="date" />
            </label>
          </div>
        </fieldset>

        <fieldset class="search-filter-group">
          <legend>Order</legend>
          <label class="search-filter-field">
            <span class="sr-only">Sort references</span>
            <select v-model="advanced.sort">
              <option value="updated_desc">Recently Updated</option>
              <option value="updated_asc">Oldest Update</option>
              <option value="year_desc">Newest Publication</option>
              <option value="year_asc">Oldest Publication</option>
              <option value="title_asc">Title</option>
            </select>
          </label>
        </fieldset>
      </div>

      <div class="search-filter-panel__actions">
        <button
          type="button"
          class="search-filter-clear"
          :disabled="draftTokens.length === 0"
          @click="clearAllFilters"
        >
          Clear All
        </button>
        <button type="submit" class="button-primary search-filter-apply">
          Show Results
        </button>
      </div>
    </section>
  </form>
</template>
