<script setup lang="ts">
const props = defineProps<{
  modelValue: string;
  disabled?: boolean;
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
  <form class="search-bar" @submit.prevent="onSubmit">
    <input
      :value="props.modelValue"
      :disabled="props.disabled"
      type="search"
      placeholder="Search by title, author, year, DOI, BibTeX key..."
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <button type="submit" :disabled="props.disabled">
      Search
    </button>
  </form>
</template>
