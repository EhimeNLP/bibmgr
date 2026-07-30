<script setup lang="ts">
import AppIcon from "./AppIcon.vue";

defineProps<{
  title: string;
  message: string;
}>();
</script>

<template>
  <div class="empty-state">
    <div class="state-icon" aria-hidden="true">
      <AppIcon name="search" />
    </div>
    <h2>{{ title }}</h2>
    <p>{{ message }}</p>
  </div>
</template>
