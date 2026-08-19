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

    <p class="reference-card__year">
      {{ reference.year ?? "Unknown year" }}
    </p>
  </button>
</template>
