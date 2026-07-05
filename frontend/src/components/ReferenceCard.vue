<script setup lang="ts">
import type { Reference } from "../types/reference";

defineProps<{
  reference: Reference;
  selected?: boolean;
}>();
</script>

<template>
  <button class="reference-card" :class="{ selected }">
    <h3>{{ reference.title || "Untitled reference" }}</h3>

    <p class="authors">
      {{ reference.authors.length > 0 ? reference.authors.join(", ") : "Unknown authors" }}
    </p>

    <p class="meta">
      <span v-if="reference.year">{{ reference.year }}</span>
      <span v-if="reference.venue"> · {{ reference.venue }}</span>
    </p>

    <p v-if="reference.doi" class="doi">
      DOI: {{ reference.doi }}
    </p>
  </button>
</template>
