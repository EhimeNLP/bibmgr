<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import {
  SYSTEM_THEME_QUERY,
  applyTheme,
  readThemePreference,
  storeThemePreference,
  type ThemePreference,
} from "../theme";
import AppIcon from "./AppIcon.vue";

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

      <AppIcon
        :name="
          option.value === 'system'
            ? 'display'
            : option.value === 'light'
              ? 'sun'
              : 'moon-stars'
        "
      />

      <span>{{ option.label }}</span>
    </label>
  </fieldset>
</template>
