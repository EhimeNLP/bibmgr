<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { exportBibtex, listBibtexExportProfiles } from "../api/bibtex";
import type {
  BibtexExportProfile,
  BibtexExportResult,
} from "../types/bibtex";
import BibtexCodeBlock from "./BibtexCodeBlock.vue";

const props = defineProps<{
  source: string;
  citationKey?: string;
}>();

const profiles = ref<BibtexExportProfile[]>([]);
const selectedProfile = ref("laboratory");
const result = ref<BibtexExportResult | null>(null);
const isLoadingProfiles = ref(false);
const isExporting = ref(false);
const profilesError = ref<string | null>(null);
const exportError = ref<string | null>(null);
const copyState = ref<"idle" | "copied" | "error">("idle");

let profilesController: AbortController | undefined;
let exportController: AbortController | undefined;
let profilesGeneration = 0;
let exportGeneration = 0;
let copyResetTimer: ReturnType<typeof setTimeout> | undefined;

const selectedProfileDetails = computed(() =>
  profiles.value.find((profile) => profile.id === selectedProfile.value),
);
const downloadFileName = computed(() => {
  const citationKey = safeFilePart(props.citationKey ?? "bibliography");
  const profile = safeFilePart(result.value?.profile ?? selectedProfile.value);
  return `${citationKey}-${profile}.bib`;
});

onMounted(() => {
  void loadProfiles();
});

watch(
  () => props.source,
  () => {
    resetCopyState();
    if (profiles.value.length > 0) void generatePreview();
  },
);

onBeforeUnmount(() => {
  profilesGeneration += 1;
  exportGeneration += 1;
  profilesController?.abort();
  exportController?.abort();
  if (copyResetTimer) clearTimeout(copyResetTimer);
});

async function loadProfiles() {
  profilesController?.abort();
  const controller = new AbortController();
  const generation = ++profilesGeneration;
  profilesController = controller;
  isLoadingProfiles.value = true;
  profilesError.value = null;

  try {
    const response = await listBibtexExportProfiles({ signal: controller.signal });
    if (generation !== profilesGeneration) return;

    const availableProfiles = response.profiles.filter(
      (profile) => profile.id.trim().length > 0,
    );
    if (availableProfiles.length === 0) {
      throw new Error("No BibTeX output profiles are available.");
    }

    profiles.value = availableProfiles;
    selectedProfile.value = preferredProfileId(availableProfiles);
    void generatePreview();
  } catch (error) {
    if (generation !== profilesGeneration || isAbortError(error)) return;
    profiles.value = [];
    result.value = null;
    profilesError.value = errorMessage(
      error,
      "Could not load BibTeX output profiles.",
    );
  } finally {
    if (generation === profilesGeneration) isLoadingProfiles.value = false;
  }
}

function preferredProfileId(availableProfiles: BibtexExportProfile[]) {
  if (availableProfiles.some((profile) => profile.id === selectedProfile.value)) {
    return selectedProfile.value;
  }
  return (
    availableProfiles.find((profile) => profile.id === "laboratory")?.id ??
    availableProfiles[0]?.id ??
    "laboratory"
  );
}

function onProfileChange() {
  resetCopyState();
  void generatePreview();
}

async function generatePreview() {
  const source = props.source;
  const profile = selectedProfile.value;
  if (!source.trim() || !profiles.value.some((item) => item.id === profile)) {
    exportController?.abort();
    exportGeneration += 1;
    result.value = null;
    exportError.value = null;
    isExporting.value = false;
    return;
  }

  exportController?.abort();
  const controller = new AbortController();
  const generation = ++exportGeneration;
  exportController = controller;
  isExporting.value = true;
  exportError.value = null;
  result.value = null;

  try {
    const exported = await exportBibtex(
      { source, profile },
      { signal: controller.signal },
    );
    if (
      generation !== exportGeneration ||
      props.source !== source ||
      selectedProfile.value !== profile
    ) {
      return;
    }
    result.value = exported;
  } catch (error) {
    if (generation !== exportGeneration || isAbortError(error)) return;
    exportError.value = errorMessage(
      error,
      "Could not generate optimized BibTeX.",
    );
  } finally {
    if (generation === exportGeneration) isExporting.value = false;
  }
}

async function copyExport() {
  if (!result.value) return;

  try {
    await writeToClipboard(result.value.source);
    copyState.value = "copied";
  } catch {
    copyState.value = "error";
  }

  if (copyResetTimer) clearTimeout(copyResetTimer);
  copyResetTimer = setTimeout(resetCopyState, 2400);
}

async function writeToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Embedded browsers may expose the API without clipboard permission.
    }
  }

  const activeElement = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "");
  textArea.style.position = "fixed";
  textArea.style.inset = "0 auto auto -9999px";
  document.body.append(textArea);
  textArea.select();
  try {
    if (!document.execCommand("copy")) throw new Error("Clipboard is unavailable.");
  } finally {
    textArea.remove();
    activeElement?.focus({ preventScroll: true });
  }
}

function downloadExport() {
  if (!result.value) return;

  const blob = new Blob([result.value.source], {
    type: "application/x-bibtex;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = downloadFileName.value;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function resetCopyState() {
  copyState.value = "idle";
  if (copyResetTimer) {
    clearTimeout(copyResetTimer);
    copyResetTimer = undefined;
  }
}

function safeFilePart(value: string) {
  return (
    value
      .trim()
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^-+|-+$/g, "") || "bibliography"
  );
}

function isAbortError(error: unknown) {
  return error instanceof Error && error.name === "AbortError";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}
</script>

<template>
  <div class="bibtex-export">
    <div class="section-header bibtex-export__header">
      <p>Generate a separate BibTeX representation for the selected output profile.</p>
      <div class="bibtex-export__actions">
        <button
          type="button"
          class="button-secondary bibtex-export__download"
          :disabled="!result || isExporting"
          @click="downloadExport"
        >
          Download .bib
        </button>
        <button
          type="button"
          class="button-secondary bibtex-export__copy"
          :class="{ success: copyState === 'copied', error: copyState === 'error' }"
          :disabled="!result || isExporting"
          @click="copyExport"
        >
          <span v-if="copyState === 'copied'">Copied</span>
          <span v-else-if="copyState === 'error'">Copy failed</span>
          <span v-else>Copy export</span>
        </button>
      </div>
    </div>

    <div class="bibtex-export__profile">
      <label for="bibtex-export-profile">Output profile</label>
      <select
        id="bibtex-export-profile"
        v-model="selectedProfile"
        :disabled="isLoadingProfiles || profiles.length === 0"
        :aria-describedby="selectedProfileDetails ? 'bibtex-export-description' : undefined"
        @change="onProfileChange"
      >
        <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
          {{ profile.display_name }}
        </option>
      </select>
    </div>

    <p
      v-if="selectedProfileDetails"
      id="bibtex-export-description"
      class="bibtex-export__description"
    >
      {{ selectedProfileDetails.description }}
    </p>

    <div
      class="bibtex-export__preview"
      :aria-busy="isLoadingProfiles || isExporting"
      aria-label="Optimized BibTeX preview"
    >
      <p v-if="isLoadingProfiles" class="bibtex-export__status" role="status">
        Loading output profiles…
      </p>
      <div v-else-if="profilesError" class="bibtex-export__error" role="alert">
        <p>{{ profilesError }}</p>
        <button type="button" class="button-secondary" @click="loadProfiles">
          Retry
        </button>
      </div>
      <p v-else-if="isExporting" class="bibtex-export__status" role="status">
        Optimizing BibTeX for {{ selectedProfileDetails?.display_name ?? selectedProfile }}…
      </p>
      <div v-else-if="exportError" class="bibtex-export__error" role="alert">
        <p>{{ exportError }}</p>
        <button type="button" class="button-secondary" @click="generatePreview">
          Retry
        </button>
      </div>
      <template v-else-if="result">
        <ul
          v-if="result.warnings.length > 0"
          class="bibtex-export__warnings"
          aria-label="Export warnings"
        >
          <li v-for="warning in result.warnings" :key="`${warning.record_index}-${warning.message}`">
            Entry {{ warning.record_index + 1 }}: {{ warning.message }}
          </li>
        </ul>
        <BibtexCodeBlock
          :source="result.source"
          accessible-label="Optimized BibTeX source"
          test-id="bibtex-export-preview"
        />
      </template>
    </div>

    <p class="sr-only" aria-live="polite">
      {{ copyState === "copied" ? "Exported BibTeX copied to clipboard." : copyState === "error" ? "Exported BibTeX could not be copied." : "" }}
    </p>
  </div>
</template>
