<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import {
  SYSTEM_THEME_QUERY,
  applyTheme,
  readThemePreference,
  storeThemePreference,
  type ThemePreference,
} from "../theme";

const options: ReadonlyArray<{
  value: ThemePreference;
  label: string;
}> = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const preference = ref<ThemePreference>("system");
let systemTheme: MediaQueryList | null = null;

function updateTheme(nextPreference: ThemePreference, persist = true) {
  preference.value = nextPreference;
  applyTheme(nextPreference, systemTheme?.matches ?? false);

  if (persist) {
    storeThemePreference(nextPreference);
  }
}

function handleSystemThemeChange(event: MediaQueryListEvent) {
  if (preference.value === "system") {
    applyTheme("system", event.matches);
  }
}

onMounted(() => {
  systemTheme = window.matchMedia(SYSTEM_THEME_QUERY);
  systemTheme.addEventListener("change", handleSystemThemeChange);
  updateTheme(readThemePreference(), false);
});

onBeforeUnmount(() => {
  systemTheme?.removeEventListener("change", handleSystemThemeChange);
});
</script>

<template>
  <fieldset class="theme-switcher">
    <legend class="sr-only">Appearance</legend>
    <label
      v-for="option in options"
      :key="option.value"
      :class="{ active: preference === option.value }"
      :title="`Use ${option.label.toLowerCase()} appearance`"
    >
      <input
        type="radio"
        name="theme-preference"
        :value="option.value"
        :checked="preference === option.value"
        @change="updateTheme(option.value)"
      />

      <svg
        v-if="option.value === 'system'"
        aria-hidden="true"
        viewBox="0 0 16 16"
        fill="none"
      >
        <rect x="2.25" y="2.75" width="11.5" height="8" rx="1.5" />
        <path d="M6 13.25h4M8 10.75v2.5" />
      </svg>

      <svg
        v-else-if="option.value === 'light'"
        aria-hidden="true"
        viewBox="0 0 16 16"
        fill="none"
      >
        <circle cx="8" cy="8" r="2.75" />
        <path d="M8 1.5v1.25M8 13.25v1.25M14.5 8h-1.25M2.75 8H1.5M12.6 3.4l-.9.9M4.3 11.7l-.9.9M12.6 12.6l-.9-.9M4.3 4.3l-.9-.9" />
      </svg>

      <svg v-else aria-hidden="true" viewBox="0 0 16 16" fill="none">
        <path d="M13.5 10.15A5.75 5.75 0 0 1 5.85 2.5a5.75 5.75 0 1 0 7.65 7.65Z" />
      </svg>

      <span>{{ option.label }}</span>
    </label>
  </fieldset>
</template>
