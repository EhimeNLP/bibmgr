<script setup lang="ts">
defineProps<{
  title: string;
  message: string;
}>();
</script>

<template>
  <div class="empty-state">
    <h2>{{ title }}</h2>
    <p>{{ message }}</p>
  </div>
</template>
