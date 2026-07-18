<script setup lang="ts">
import type { Reference } from "../types/reference";
import ReferenceCard from "./ReferenceCard.vue";

defineProps<{
  references: Reference[];
  selectedReferenceId?: string;
}>();

const emit = defineEmits<{
  select: [reference: Reference, event: MouseEvent];
}>();
</script>

<template>
  <ul class="reference-list">
    <li v-for="reference in references" :key="reference.id">
      <ReferenceCard
        :reference="reference"
        :selected="reference.id === selectedReferenceId"
        @click="emit('select', reference, $event)"
      />
    </li>
  </ul>
</template>
