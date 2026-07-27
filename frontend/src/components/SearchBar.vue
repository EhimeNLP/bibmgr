<script setup lang="ts">
import { reactive } from "vue";
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

const advanced = reactive({
  year: "",
  author: "",
  venue: "",
  identifier: "",
  entryType: "",
  createdBy: "",
  updatedFrom: "",
  updatedTo: "",
  sort: "updated_desc" as ReferenceSort,
});

function onSubmit() {
  const parsedYear = Number.parseInt(advanced.year, 10);
  emit("search", {
    query: props.modelValue,
    year: Number.isInteger(parsedYear) ? parsedYear : undefined,
    author: advanced.author,
    venue: advanced.venue,
    identifier: advanced.identifier,
    entryType: advanced.entryType,
    createdBy: advanced.createdBy,
    updatedFrom: advanced.updatedFrom
      ? new Date(`${advanced.updatedFrom}T00:00:00`).toISOString()
      : undefined,
    updatedTo: advanced.updatedTo
      ? new Date(`${advanced.updatedTo}T23:59:59.999`).toISOString()
      : undefined,
    sort: advanced.sort,
  });
}
</script>

<template>
  <form class="search-bar" role="search" :aria-busy="props.loading" @submit.prevent="onSubmit">
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
        placeholder="Title, author, year, DOI, or BibTeX key"
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
    <details class="search-filters">
      <summary>Filters and sorting</summary>
      <div class="search-filters__grid">
        <label>
          <span>Year</span>
          <input
            v-model="advanced.year"
            type="number"
            min="1"
            max="9999"
            inputmode="numeric"
          />
        </label>
        <label>
          <span>Author</span>
          <input v-model="advanced.author" type="search" />
        </label>
        <label>
          <span>Venue</span>
          <input v-model="advanced.venue" type="search" />
        </label>
        <label>
          <span>DOI or identifier</span>
          <input v-model="advanced.identifier" type="search" />
        </label>
        <label>
          <span>Entry type</span>
          <input
            v-model="advanced.entryType"
            type="search"
            placeholder="article"
          />
        </label>
        <label>
          <span>Created by</span>
          <input
            v-model="advanced.createdBy"
            type="search"
            placeholder="member@…"
          />
        </label>
        <label>
          <span>Updated from</span>
          <input v-model="advanced.updatedFrom" type="date" />
        </label>
        <label>
          <span>Updated through</span>
          <input v-model="advanced.updatedTo" type="date" />
        </label>
        <label>
          <span>Sort</span>
          <select v-model="advanced.sort">
            <option value="updated_desc">Recently updated</option>
            <option value="updated_asc">Oldest update</option>
            <option value="year_desc">Newest publication</option>
            <option value="year_asc">Oldest publication</option>
            <option value="title_asc">Title</option>
          </select>
        </label>
      </div>
    </details>
  </form>
</template>
