<script setup lang="ts">
defineProps<{
  title: string;
  message: string;
}>();
</script>

<template>
  <div class="empty-state">
    <div class="state-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m15.5 15.5 4 4M8 10.5h5" />
      </svg>
    </div>
    <h2>{{ title }}</h2>
    <p>{{ message }}</p>
  </div>
</template>
