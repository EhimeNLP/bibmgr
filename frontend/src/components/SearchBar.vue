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
import AppIcon from "./AppIcon.vue";

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
  | "updatedTo";

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
};

const defaultSort: ReferenceSort = "updated_desc";
const root = ref<HTMLFormElement | null>(null);
const filterButton = ref<HTMLButtonElement | null>(null);
const filterPanel = ref<HTMLElement | null>(null);
const sortButton = ref<HTMLButtonElement | null>(null);
const sortMenu = ref<HTMLElement | null>(null);
const filtersOpen = ref(false);
const sortOpen = ref(false);
const selectedSort = ref<ReferenceSort>(defaultSort);
const advanced = reactive<AdvancedFilters>(initialAdvancedFilters());
const applied = reactive<AdvancedFilters>(initialAdvancedFilters());

const sortLabels: Record<ReferenceSort, string> = {
  updated_desc: "Recently Updated",
  updated_asc: "Oldest Update",
  year_desc: "Newest Publication",
  year_asc: "Oldest Publication",
  title_asc: "Title A–Z",
};
const sortOptions = (
  Object.entries(sortLabels) as Array<[ReferenceSort, string]>
).map(([value, label]) => ({ value, label }));

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
  return tokens;
}

const filterButtonLabel = computed(() => {
  const count = activeTokens.value.length;
  if (count === 0) return "Show search filters";
  return `Show search filters, ${count} active`;
});
const sortButtonLabel = computed(
  () => `Sort references: ${sortLabels[selectedSort.value]}`,
);

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
    sort: selectedSort.value,
  };
}

function onSubmit() {
  Object.assign(applied, advanced);
  filtersOpen.value = false;
  sortOpen.value = false;
  emit("search", buildFilters(applied));
}

function toggleFilters() {
  if (filtersOpen.value) {
    closeFilters();
    return;
  }

  closeSort();
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

function toggleSort() {
  if (sortOpen.value) {
    closeSort();
    return;
  }

  closeFilters();
  sortOpen.value = true;
  void nextTick(() => {
    sortMenu.value
      ?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
      ?.focus({ preventScroll: true });
  });
}

function closeSort({ restoreFocus = false } = {}) {
  if (!sortOpen.value) return;
  sortOpen.value = false;
  if (restoreFocus) {
    void nextTick(() => sortButton.value?.focus({ preventScroll: true }));
  }
}

function closeOpenPopover({ restoreFocus = false } = {}) {
  if (filtersOpen.value) {
    closeFilters({ restoreFocus });
  } else if (sortOpen.value) {
    closeSort({ restoreFocus });
  }
}

function closeWhenClickingOutside(event: PointerEvent) {
  if (
    (!filtersOpen.value && !sortOpen.value) ||
    !(event.target instanceof Node)
  ) {
    return;
  }
  if (!root.value?.contains(event.target)) {
    closeFilters();
    closeSort();
  }
}

function applySort(sort: ReferenceSort) {
  selectedSort.value = sort;
  closeSort({ restoreFocus: true });
  emit("search", buildFilters(applied));
}

function navigateSortMenu(event: KeyboardEvent) {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  const options = Array.from(
    sortMenu.value?.querySelectorAll<HTMLButtonElement>(
      '[role="menuitemradio"]',
    ) ?? [],
  );
  if (options.length === 0) return;

  event.preventDefault();
  const currentIndex = options.findIndex(
    (option) => option === document.activeElement,
  );
  let nextIndex = currentIndex;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = options.length - 1;
  if (event.key === "ArrowDown") {
    nextIndex = currentIndex < options.length - 1 ? currentIndex + 1 : 0;
  }
  if (event.key === "ArrowUp") {
    nextIndex = currentIndex > 0 ? currentIndex - 1 : options.length - 1;
  }
  options[nextIndex]?.focus({ preventScroll: true });
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
    @keydown.esc.stop.prevent="closeOpenPopover({ restoreFocus: true })"
  >
    <div class="search-bar__controls">
      <label class="sr-only" for="reference-search">Search references</label>
      <div class="search-input">
        <AppIcon name="search" />
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
        <AppIcon v-else name="search" />
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
        <AppIcon name="sliders" />
        <span
          v-if="activeTokens.length > 0"
          class="search-filter-trigger__count"
          aria-hidden="true"
        >
          {{ activeTokens.length }}
        </span>
      </button>
      <button
        ref="sortButton"
        type="button"
        class="search-sort-trigger"
        :class="{ active: sortOpen || selectedSort !== defaultSort }"
        :disabled="props.disabled"
        :aria-expanded="sortOpen"
        :aria-label="sortButtonLabel"
        aria-controls="reference-search-sort"
        aria-haspopup="menu"
        :title="sortButtonLabel"
        @click="toggleSort"
      >
        <AppIcon name="sort-down" />
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
        <AppIcon name="x" />
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
          <AppIcon name="x-lg" />
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

    <section
      v-if="sortOpen"
      id="reference-search-sort"
      ref="sortMenu"
      class="search-sort-menu"
      role="menu"
      aria-label="Sort references"
      @keydown="navigateSortMenu"
    >
      <p>Sort by</p>
      <button
        v-for="option in sortOptions"
        :key="option.value"
        type="button"
        role="menuitemradio"
        :aria-checked="selectedSort === option.value"
        @click="applySort(option.value)"
      >
        <span>{{ option.label }}</span>
        <AppIcon
          v-if="selectedSort === option.value"
          name="check-lg"
        />
      </button>
    </section>
  </form>
</template>
