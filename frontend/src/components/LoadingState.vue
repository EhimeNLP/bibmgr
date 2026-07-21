<template>
  <div class="loading-state" role="status" aria-live="polite">
    <span class="sr-only">Loading references…</span>
    <div v-for="index in 3" :key="index" class="skeleton-card" aria-hidden="true">
      <span class="skeleton-line skeleton-line--title" />
      <span class="skeleton-line" />
      <span class="skeleton-line skeleton-line--short" />
    </div>
  </div>
</template>
