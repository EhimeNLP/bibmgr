<script setup lang="ts">
const props = defineProps<{
  modelValue: string;
  disabled?: boolean;
  loading?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
  search: [];
}>();

function onSubmit() {
  emit("search");
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
  </form>
</template>
