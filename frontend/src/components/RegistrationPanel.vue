<script setup lang="ts">
import { computed, ref } from "vue";
import {
  registerBibtexToDatabase,
  uploadPdfForRegistration,
} from "../api/registration";
import type {
  Reference,
  RegistrationReviewItem,
  RegistrationStatus,
} from "../types/reference";

type RegistrationMode = "pdf" | "bibtex";

const emit = defineEmits<{
  registered: [reference: Reference];
}>();

const mode = ref<RegistrationMode>("pdf");
const selectedPdf = ref<File | null>(null);
const uploadId = ref<string | undefined>();
const reviewItems = ref<RegistrationReviewItem[]>([]);
const isPdfProcessing = ref(false);
const pdfError = ref<string | null>(null);
const pdfMessage = ref<string | null>(null);
const registeringItemIds = ref<Set<string>>(new Set());

const directBibtex = ref("");
const isDirectRegistering = ref(false);
const directError = ref<string | null>(null);
const directMessage = ref<string | null>(null);

const selectedPdfName = computed(() => selectedPdf.value?.name ?? "No PDF selected");
const canProcessPdf = computed(() => Boolean(selectedPdf.value) && !isPdfProcessing.value);
const canRegisterDirectBibtex = computed(
  () => directBibtex.value.trim().length > 0 && !isDirectRegistering.value,
);

function selectMode(nextMode: RegistrationMode) {
  mode.value = nextMode;
}

function onPdfChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedPdf.value = input.files?.[0] ?? null;
  pdfError.value = null;
  pdfMessage.value = null;
}

async function processPdf() {
  if (!selectedPdf.value) return;

  isPdfProcessing.value = true;
  pdfError.value = null;
  pdfMessage.value = null;
  reviewItems.value = [];

  try {
    const result = await uploadPdfForRegistration(selectedPdf.value);
    uploadId.value = result.uploadId;
    reviewItems.value = result.references;
    pdfMessage.value =
      result.references.length > 0
        ? `${result.references.length} references ready for review.`
        : "No references returned from PDF processing.";
  } catch (error) {
    pdfError.value =
      error instanceof Error ? error.message : "Failed to process PDF.";
  } finally {
    isPdfProcessing.value = false;
  }
}

async function registerReviewItem(item: RegistrationReviewItem) {
  if (!item.bibtex.trim()) {
    item.registrationState = "failed";
    item.registrationMessage = "BibTeX is empty.";
    return;
  }

  setItemRegistering(item.id, true);
  item.registrationMessage = undefined;

  try {
    const result = await registerBibtexToDatabase({
      bibtex: item.bibtex,
      source: "pdf",
      uploadId: uploadId.value,
      reviewItemId: item.id,
      metadata: {
        title: item.title,
        authors: item.authors,
        year: item.year,
        venue: item.venue,
        doi: item.doi,
      },
    });
    item.registrationState = "registered";
    item.registrationMessage = "Registered.";
    emit("registered", result.reference);
  } catch (error) {
    item.registrationState = "failed";
    item.registrationMessage =
      error instanceof Error ? error.message : "Failed to register BibTeX.";
  } finally {
    setItemRegistering(item.id, false);
  }
}

async function registerDirectBibtex() {
  if (!directBibtex.value.trim()) return;

  isDirectRegistering.value = true;
  directError.value = null;
  directMessage.value = null;

  try {
    const result = await registerBibtexToDatabase({
      bibtex: directBibtex.value,
      source: "manual",
    });
    directBibtex.value = "";
    directMessage.value = "Registered.";
    emit("registered", result.reference);
  } catch (error) {
    directError.value =
      error instanceof Error ? error.message : "Failed to register BibTeX.";
  } finally {
    isDirectRegistering.value = false;
  }
}

function setItemRegistering(id: string, isRegistering: boolean) {
  const nextIds = new Set(registeringItemIds.value);
  if (isRegistering) {
    nextIds.add(id);
  } else {
    nextIds.delete(id);
  }
  registeringItemIds.value = nextIds;
}

function isItemRegistering(id: string) {
  return registeringItemIds.value.has(id);
}

function reviewMeta(item: RegistrationReviewItem) {
  const parts = [
    item.authors.length > 0 ? item.authors.join(", ") : null,
    item.year ? String(item.year) : null,
    item.venue ?? null,
    item.doi ? `DOI: ${item.doi}` : null,
  ].filter((part): part is string => Boolean(part));

  return parts.length > 0 ? parts.join(" · ") : "Metadata unavailable";
}

function statusLabel(status: RegistrationStatus) {
  const labels: Record<RegistrationStatus, string> = {
    success: "Success",
    needs_review: "Needs review",
    not_found: "Not found",
    api_error: "API error",
  };
  return labels[status];
}
</script>

<template>
  <section class="registration-panel">
    <div class="registration-header">
      <h2>Register</h2>
      <div class="mode-tabs" role="tablist" aria-label="Registration mode">
        <button
          type="button"
          :class="{ active: mode === 'pdf' }"
          @click="selectMode('pdf')"
        >
          PDF
        </button>
        <button
          type="button"
          :class="{ active: mode === 'bibtex' }"
          @click="selectMode('bibtex')"
        >
          BibTeX
        </button>
      </div>
    </div>

    <div v-if="mode === 'pdf'" class="registration-body">
      <div class="registration-controls">
        <label class="file-picker">
          <input type="file" accept="application/pdf,.pdf" @change="onPdfChange" />
          <span>{{ selectedPdfName }}</span>
        </label>
        <button type="button" :disabled="!canProcessPdf" @click="processPdf">
          {{ isPdfProcessing ? "Processing..." : "Process PDF" }}
        </button>
      </div>

      <p v-if="pdfError" class="registration-error">{{ pdfError }}</p>
      <p v-else-if="pdfMessage" class="registration-message">{{ pdfMessage }}</p>

      <div v-if="reviewItems.length > 0" class="review-list">
        <article
          v-for="item in reviewItems"
          :key="item.id"
          class="review-item"
        >
          <div class="review-item-header">
            <div>
              <h3>{{ item.title || "Untitled reference" }}</h3>
              <p>{{ reviewMeta(item) }}</p>
            </div>
            <span class="status-pill" :class="item.status">
              {{ statusLabel(item.status) }}
            </span>
          </div>

          <textarea
            v-model="item.bibtex"
            rows="8"
            spellcheck="false"
            aria-label="Review BibTeX"
          />

          <div class="registration-actions">
            <p
              v-if="item.registrationMessage"
              :class="{
                'registration-error': item.registrationState === 'failed',
                'registration-message': item.registrationState === 'registered',
              }"
            >
              {{ item.registrationMessage }}
            </p>
            <button
              type="button"
              :disabled="isItemRegistering(item.id)"
              @click="registerReviewItem(item)"
            >
              {{ isItemRegistering(item.id) ? "Registering..." : "Register" }}
            </button>
          </div>
        </article>
      </div>
    </div>

    <div v-else class="registration-body">
      <textarea
        v-model="directBibtex"
        rows="8"
        spellcheck="false"
        placeholder="@article{...}"
        aria-label="BibTeX"
      />

      <div class="registration-actions">
        <p v-if="directError" class="registration-error">{{ directError }}</p>
        <p v-else-if="directMessage" class="registration-message">
          {{ directMessage }}
        </p>
        <button
          type="button"
          :disabled="!canRegisterDirectBibtex"
          @click="registerDirectBibtex"
        >
          {{ isDirectRegistering ? "Registering..." : "Register BibTeX" }}
        </button>
      </div>
    </div>
  </section>
</template>
