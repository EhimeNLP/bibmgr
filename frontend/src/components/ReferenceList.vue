<script setup lang="ts">
import type { Reference } from "../types/reference";
import ReferenceCard from "./ReferenceCard.vue";

defineProps<{
  references: Reference[];
  selectedReferenceId?: string;
}>();

const emit = defineEmits<{
  select: [reference: Reference];
}>();
</script>

<template>
  <section class="reference-list">
    <ReferenceCard
      v-for="reference in references"
      :key="reference.id"
      :reference="reference"
      :selected="reference.id === selectedReferenceId"
      @click="emit('select', reference)"
    />
  </section>
</template>
