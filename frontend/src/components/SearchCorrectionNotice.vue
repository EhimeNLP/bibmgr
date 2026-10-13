<script setup lang="ts">
import { computed } from "vue";
import { diffWordsWithSpace } from "diff";
import type { SearchCorrection } from "../types/reference";

const props = defineProps<{ correction: SearchCorrection }>();
defineEmits<{ "search-original": [] }>();

const changes = computed(() => diffWordsWithSpace(
  props.correction.originalQuery,
  props.correction.correctedQuery,
));
const corrected = computed(() => changes.value.filter((part) => !part.removed));
const original = computed(() => changes.value.filter((part) => !part.added));
</script>

<template>
  <div class="search-correction-notice" role="status" aria-live="polite">
    <p>
      Showing results for
      <span class="search-correction-query">
        <template v-for="(part, index) in corrected" :key="index">
          <strong v-if="part.added"><em>{{ part.value }}</em></strong>
          <template v-else>{{ part.value }}</template>
        </template>
      </span>
    </p>
    <button type="button" @click="$emit('search-original')">
      Search instead for
      <span class="search-correction-query">
        <template v-for="(part, index) in original" :key="index">
          <strong v-if="part.removed"><em>{{ part.value }}</em></strong>
          <template v-else>{{ part.value }}</template>
        </template>
      </span>
    </button>
  </div>
</template>
