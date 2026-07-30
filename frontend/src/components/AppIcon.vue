<script setup lang="ts">
defineProps<{
  name: string;
}>();
</script>

<template>
  <i class="app-icon bi" :class="`bi-${name}`" aria-hidden="true"></i>
</template>
