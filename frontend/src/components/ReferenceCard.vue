<script setup lang="ts">
import type { Reference } from "../types/reference";

defineProps<{
  reference: Reference;
  selected?: boolean;
}>();
</script>

<template>
  <button
    type="button"
    class="reference-card"
    :class="{ selected }"
    :aria-current="selected ? 'true' : undefined"
  >
    <div class="reference-card__header">
      <h3>{{ reference.title || "Untitled reference" }}</h3>
    </div>

    <p class="authors">
      {{ reference.authors.length > 0 ? reference.authors.join(", ") : "Unknown authors" }}
    </p>

    <div class="reference-card__meta">
      <span v-if="reference.year">{{ reference.year }}</span>
      <span v-if="reference.venue">{{ reference.venue }}</span>
    </div>

    <p v-if="reference.doi" class="doi">
      <span>DOI</span> {{ reference.doi }}
    </p>
  </button>
</template>
