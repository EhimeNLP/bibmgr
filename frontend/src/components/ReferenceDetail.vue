<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import type { Reference } from "../types/reference";
import BibtexCodeBlock from "./BibtexCodeBlock.vue";
import BibtexExportPanel from "./BibtexExportPanel.vue";

type BibtexView = "stored" | "export";

const props = defineProps<{
  reference: Reference | null;
}>();

const copyState = ref<"idle" | "copied" | "error">("idle");
const activeBibtexView = ref<BibtexView>("stored");
const hasOpenedExport = ref(false);
let copyResetTimer: ReturnType<typeof setTimeout> | undefined;

watch(
  () => props.reference?.id,
  () => {
    activeBibtexView.value = "stored";
    hasOpenedExport.value = false;
    resetCopyState();
  },
);

onBeforeUnmount(() => {
  if (copyResetTimer) clearTimeout(copyResetTimer);
});

async function copyText(text?: string) {
  if (!text) return;

  try {
    await writeToClipboard(text);
    copyState.value = "copied";
  } catch {
    copyState.value = "error";
  }

  if (copyResetTimer) clearTimeout(copyResetTimer);
  copyResetTimer = setTimeout(resetCopyState, 2400);
}

async function writeToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    try {
      await Promise.race([
        navigator.clipboard.writeText(text),
        new Promise<never>((_, reject) => {
          timeoutId = setTimeout(() => reject(new Error("Clipboard timed out.")), 600);
        }),
      ]);
      return;
    } catch {
      // Some embedded browsers expose the Clipboard API without granting access.
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
    }
  }

  if (!copyWithSelection(text)) {
    throw new Error("Clipboard is unavailable.");
  }
}

function copyWithSelection(text: string) {
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
    return document.execCommand("copy");
  } finally {
    textArea.remove();
    activeElement?.focus({ preventScroll: true });
  }
}

function resetCopyState() {
  copyState.value = "idle";
  if (copyResetTimer) {
    clearTimeout(copyResetTimer);
    copyResetTimer = undefined;
  }
}

function selectBibtexView(view: BibtexView, moveFocus = false) {
  if (view === "export") hasOpenedExport.value = true;
  activeBibtexView.value = view;

  if (moveFocus) {
    void nextTick(() => {
      document.getElementById(`bibtex-tab-${view}`)?.focus();
    });
  }
}

function onBibtexTabsKeydown(event: KeyboardEvent) {
  const target = event.target;
  if (!(target instanceof HTMLElement) || target.getAttribute("role") !== "tab") {
    return;
  }

  const view = target.dataset.bibtexView as BibtexView | undefined;
  let nextView: BibtexView | undefined;

  if (event.key === "ArrowRight") {
    nextView = view === "stored" ? "export" : "stored";
  } else if (event.key === "ArrowLeft") {
    nextView = view === "export" ? "stored" : "export";
  } else if (event.key === "Home") {
    nextView = "stored";
  } else if (event.key === "End") {
    nextView = "export";
  }

  if (!nextView) return;
  event.preventDefault();
  selectBibtexView(nextView, true);
}
</script>

<template>
  <section class="reference-detail">
    <div v-if="!reference" class="placeholder">
      <div class="state-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M6.75 4.75h8.5a2 2 0 0 1 2 2v12.5h-8.5a2 2 0 0 0-2 2V4.75Z" />
          <path d="M6.75 4.75H5.5a2 2 0 0 0-2 2v10.5a2 2 0 0 0 2 2h1.25" />
        </svg>
      </div>
      <h2>Select a reference</h2>
      <p>Choose an item from the library to view its metadata and BibTeX.</p>
    </div>

    <template v-else>
      <header class="detail-header">
        <div>
          <h2>{{ reference.title || "Untitled reference" }}</h2>
        </div>
        <a
          v-if="reference.url"
          class="source-link"
          :href="reference.url"
          target="_blank"
          rel="noopener noreferrer"
        >
          <span>Open source</span>
          <svg aria-hidden="true" viewBox="0 0 16 16" fill="none">
            <path d="M6 3h7v7M13 3 5 11" />
            <path d="M11 9v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h3" />
          </svg>
        </a>
      </header>

      <div class="detail-section">
        <h3>Metadata</h3>
        <dl class="metadata-list">
          <div class="metadata-row">
            <dt>Authors</dt>
            <dd>{{ reference.authors.length > 0 ? reference.authors.join(", ") : "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>Year</dt>
            <dd>{{ reference.year ?? "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>Venue</dt>
            <dd>{{ reference.venue || "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>DOI</dt>
            <dd>{{ reference.doi || "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>BibTeX Key</dt>
            <dd>{{ reference.bibtexKey || "Unknown" }}</dd>
          </div>
        </dl>
      </div>

      <div class="detail-section bibtex-detail">
        <div class="section-header">
          <h3>BibTeX</h3>
          <button
            v-if="reference.bibtex && activeBibtexView === 'stored'"
            type="button"
            class="button-secondary copy-button"
            :class="{ success: copyState === 'copied', error: copyState === 'error' }"
            @click="copyText(reference.bibtex)"
          >
            <svg aria-hidden="true" viewBox="0 0 18 18" fill="none">
              <path v-if="copyState === 'copied'" d="m4 9 3 3 7-7" />
              <template v-else>
                <rect x="6" y="5" width="8" height="9" rx="1.5" />
                <path d="M11.5 5V4A1.5 1.5 0 0 0 10 2.5H4A1.5 1.5 0 0 0 2.5 4v7A1.5 1.5 0 0 0 4 12.5h2" />
              </template>
            </svg>
            <span v-if="copyState === 'copied'">Copied</span>
            <span v-else-if="copyState === 'error'">Copy failed</span>
            <span v-else>Copy</span>
          </button>
        </div>

        <p class="sr-only" aria-live="polite">
          {{ copyState === "copied" ? "BibTeX copied to clipboard." : copyState === "error" ? "BibTeX could not be copied." : "" }}
        </p>

        <template v-if="reference.bibtex">
          <div
            class="bibtex-view-tabs"
            role="tablist"
            aria-label="BibTeX views"
            @keydown="onBibtexTabsKeydown"
          >
            <button
              id="bibtex-tab-stored"
              type="button"
              role="tab"
              data-bibtex-view="stored"
              :aria-selected="activeBibtexView === 'stored'"
              aria-controls="bibtex-panel-stored"
              :tabindex="activeBibtexView === 'stored' ? 0 : -1"
              @click="selectBibtexView('stored')"
            >
              Stored source
            </button>
            <button
              id="bibtex-tab-export"
              type="button"
              role="tab"
              data-bibtex-view="export"
              :aria-selected="activeBibtexView === 'export'"
              aria-controls="bibtex-panel-export"
              :tabindex="activeBibtexView === 'export' ? 0 : -1"
              @click="selectBibtexView('export')"
            >
              Export preview
            </button>
          </div>

          <div
            v-show="activeBibtexView === 'stored'"
            id="bibtex-panel-stored"
            class="bibtex-tabpanel"
            role="tabpanel"
            aria-labelledby="bibtex-tab-stored"
          >
            <BibtexCodeBlock
              :source="reference.bibtex"
              accessible-label="Stored BibTeX source"
              test-id="bibtex-stored-source"
            />
          </div>

          <div
            v-show="activeBibtexView === 'export'"
            id="bibtex-panel-export"
            class="bibtex-tabpanel"
            role="tabpanel"
            aria-labelledby="bibtex-tab-export"
          >
            <BibtexExportPanel
              v-if="hasOpenedExport"
              :source="reference.bibtex"
              :citation-key="reference.bibtexKey"
            />
          </div>
        </template>
        <p v-else class="muted">BibTeX has not been reconstructed yet.</p>
      </div>
    </template>
  </section>
</template>
