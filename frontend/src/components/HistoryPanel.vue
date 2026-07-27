<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import {
  getReferenceHistory,
  pageReferenceHistory,
  revertReference,
} from "../api/history";
import type {
  ReferenceHistory,
  ReferenceHistoryAction,
  ReferenceHistorySummary,
  ReferenceRevision,
} from "../types/history";
import type { Reference } from "../types/reference";
import BibtexCodeBlock from "./BibtexCodeBlock.vue";

const props = defineProps<{
  authenticated: boolean;
}>();

const emit = defineEmits<{
  restored: [reference: Reference];
  loginRequired: [];
}>();

const isOpen = ref(false);
const isLoading = ref(false);
const isRestoring = ref(false);
const summaries = ref<ReferenceHistorySummary[]>([]);
const selectedReferenceId = ref<string | null>(null);
const history = ref<ReferenceHistory | null>(null);
const pendingRevision = ref<number | null>(null);
const errorMessage = ref<string | null>(null);
const statusMessage = ref<string | null>(null);
const catalogTotal = ref(0);
const catalogOffset = ref(0);
const catalogLimit = 25;
const dialog = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);

const selectedSummary = computed(
  () =>
    summaries.value.find(
      (summary) => summary.referenceId === selectedReferenceId.value,
    ) ?? null,
);
const catalogPage = computed(
  () => Math.floor(catalogOffset.value / catalogLimit) + 1,
);
const catalogPageCount = computed(() =>
  Math.max(1, Math.ceil(catalogTotal.value / catalogLimit)),
);

watch(
  () => props.authenticated,
  (authenticated) => {
    if (!authenticated && isOpen.value) void closeHistory();
  },
);

onBeforeUnmount(() => {
  document.body.classList.remove("history-open");
});

async function openHistory() {
  if (!props.authenticated) {
    emit("loginRequired");
    return;
  }
  isOpen.value = true;
  document.body.classList.add("history-open");
  await nextTick();
  dialog.value?.focus({ preventScroll: true });
  await loadCatalog();
}

async function closeHistory() {
  isOpen.value = false;
  document.body.classList.remove("history-open");
  pendingRevision.value = null;
  await nextTick();
  trigger.value?.focus({ preventScroll: true });
}

async function loadCatalog() {
  isLoading.value = true;
  errorMessage.value = null;
  try {
    const page = await pageReferenceHistory({
      limit: catalogLimit,
      offset: catalogOffset.value,
    });
    summaries.value = page.items;
    catalogTotal.value = page.total;
    catalogOffset.value = page.offset;
    const selectedStillExists = summaries.value.some(
      (summary) => summary.referenceId === selectedReferenceId.value,
    );
    selectedReferenceId.value = selectedStillExists
      ? selectedReferenceId.value
      : (summaries.value[0]?.referenceId ?? null);
    if (selectedReferenceId.value) {
      await loadHistory(selectedReferenceId.value, false);
    } else {
      history.value = null;
    }
  } catch (error) {
    errorMessage.value = errorText(error, "Could not load history.");
  } finally {
    isLoading.value = false;
  }
}

async function selectHistory(referenceId: string) {
  selectedReferenceId.value = referenceId;
  pendingRevision.value = null;
  statusMessage.value = null;
  await loadHistory(referenceId);
}

async function loadHistory(referenceId: string, showLoading = true) {
  if (showLoading) isLoading.value = true;
  errorMessage.value = null;
  try {
    history.value = await getReferenceHistory(referenceId);
  } catch (error) {
    errorMessage.value = errorText(error, "Could not load revisions.");
    history.value = null;
  } finally {
    if (showLoading) isLoading.value = false;
  }
}

function requestRestore(revision: number) {
  pendingRevision.value = revision;
  statusMessage.value = null;
}

async function confirmRestore() {
  if (
    !history.value ||
    pendingRevision.value === null ||
    isRestoring.value
  ) {
    return;
  }
  isRestoring.value = true;
  errorMessage.value = null;
  const targetRevision = pendingRevision.value;

  try {
    const restored = await revertReference(
      history.value.referenceId,
      targetRevision,
      history.value.headRevision,
    );
    emit("restored", restored);
    statusMessage.value = `Revision ${targetRevision} was restored as a new revision.`;
    pendingRevision.value = null;
    await loadCatalog();
  } catch (error) {
    errorMessage.value = errorText(error, "Could not restore the revision.");
    await loadCatalog();
  } finally {
    isRestoring.value = false;
  }
}

function canRestore(revision: ReferenceRevision): boolean {
  return Boolean(
    history.value &&
      revision.restorable &&
      !(
        history.value.exists &&
        revision.revision === history.value.headRevision
      ),
  );
}

function sourceWasCanonicalized(revision: ReferenceRevision): boolean {
  return Boolean(
    revision.submittedBibtex &&
      revision.canonicalBibtex &&
      revision.submittedBibtex !== revision.canonicalBibtex,
  );
}

function actionLabel(action: ReferenceHistoryAction): string {
  return {
    baseline: "Baseline captured",
    create: "Created",
    update: "Edited",
    delete: "Deleted",
      restore: "Restored",
      context: "Citation contexts added",
  }[action];
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function onDialogKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeHistory();
    return;
  }
  trapDialogFocus(event, dialog.value);
}

async function changeCatalogPage(direction: -1 | 1) {
  const nextOffset = catalogOffset.value + direction * catalogLimit;
  if (nextOffset < 0 || nextOffset >= catalogTotal.value) return;
  catalogOffset.value = nextOffset;
  selectedReferenceId.value = null;
  history.value = null;
  await loadCatalog();
}

function trapDialogFocus(event: KeyboardEvent, root: HTMLElement | null) {
  if (event.key !== "Tab" || !root) return;
  const focusable = Array.from(
    root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.getClientRects().length > 0);
  const first = focusable[0];
  const last = focusable.at(-1);
  if (!first || !last) return;
  if (
    event.shiftKey &&
    (document.activeElement === first || document.activeElement === root)
  ) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
</script>

<template>
  <div class="history-panel">
    <button
      ref="trigger"
      type="button"
      class="history-trigger"
      aria-label="Reference history"
      aria-haspopup="dialog"
      :aria-expanded="isOpen"
      :title="authenticated ? 'Reference history' : 'Log in to view history'"
      @click="openHistory"
    >
      <svg aria-hidden="true" viewBox="0 0 18 18" fill="none">
        <path d="M4.2 5.3A6 6 0 1 1 3 9" />
        <path d="M1.8 4.2v3.2H5M9 5.5V9l2.3 1.4" />
      </svg>
      <span>History</span>
    </button>

    <Teleport v-if="isOpen" to="body">
      <div
        class="history-backdrop"
        @click.self="closeHistory"
      >
        <section
          ref="dialog"
          class="history-sheet"
          role="dialog"
          aria-modal="true"
          aria-labelledby="history-heading"
          tabindex="-1"
          @keydown="onDialogKeydown"
        >
          <header class="history-sheet__header">
            <div>
              <p class="auth-eyebrow">Append-only revisions</p>
              <h2 id="history-heading">Reference history</h2>
              <p>Deleted references remain available for restoration.</p>
            </div>
            <button
              type="button"
              class="registration-close"
              aria-label="Close history"
              @click="closeHistory"
            >
              <svg aria-hidden="true" viewBox="0 0 18 18" fill="none">
                <path d="m5 5 8 8M13 5l-8 8" />
              </svg>
            </button>
          </header>

          <p v-if="errorMessage" class="history-alert" role="alert">
            {{ errorMessage }}
          </p>
          <p v-else-if="statusMessage" class="history-status" role="status">
            {{ statusMessage }}
          </p>

          <div v-if="isLoading && summaries.length === 0" class="history-empty">
            Loading history…
          </div>
          <div v-else-if="summaries.length === 0" class="history-empty">
            No reference revisions have been recorded.
          </div>
          <div v-else class="history-layout">
            <nav class="history-catalog" aria-label="References with history">
              <button
                v-for="summary in summaries"
                :key="summary.referenceId"
                type="button"
                :class="{ active: summary.referenceId === selectedReferenceId }"
                @click="selectHistory(summary.referenceId)"
              >
                <strong>{{ summary.title || "Untitled reference" }}</strong>
                <span>
                  Revision {{ summary.headRevision }}
                  · {{ summary.exists ? "Active" : "Deleted" }}
                </span>
              </button>
              <div
                v-if="catalogTotal > catalogLimit"
                class="history-pagination"
              >
                <button
                  type="button"
                  class="button-secondary"
                  :disabled="catalogOffset === 0"
                  @click="changeCatalogPage(-1)"
                >
                  Previous
                </button>
                <span>
                  {{ catalogPage }} / {{ catalogPageCount }}
                </span>
                <button
                  type="button"
                  class="button-secondary"
                  :disabled="
                    catalogOffset + catalogLimit >= catalogTotal
                  "
                  @click="changeCatalogPage(1)"
                >
                  Next
                </button>
              </div>
            </nav>

            <div class="history-revisions">
              <div v-if="selectedSummary" class="history-current">
                <div>
                  <h3>{{ selectedSummary.title || "Untitled reference" }}</h3>
                  <p>{{ selectedSummary.referenceId }}</p>
                </div>
                <span :class="{ deleted: !selectedSummary.exists }">
                  {{ selectedSummary.exists ? "Active" : "Deleted" }}
                </span>
              </div>

              <ol v-if="history" class="history-list">
                <li
                  v-for="revision in history.revisions"
                  :key="revision.revision"
                >
                  <div class="history-revision__main">
                    <div class="history-revision__heading">
                      <strong>
                        Revision {{ revision.revision }}
                        · {{ actionLabel(revision.action) }}
                      </strong>
                      <span>{{ formatDate(revision.occurredAt) }}</span>
                    </div>
                    <p>{{ revision.actor.email }}</p>
                    <p v-if="revision.restoredFromRevision">
                      Restored from revision {{ revision.restoredFromRevision }}
                    </p>
                    <details
                      v-if="revision.canonicalBibtex"
                      class="history-revision__source"
                    >
                      <summary>
                        {{
                          sourceWasCanonicalized(revision)
                            ? "View submitted and laboratory BibTeX"
                            : "View laboratory BibTeX"
                        }}
                      </summary>
                      <template v-if="sourceWasCanonicalized(revision)">
                        <h4>Submitted source</h4>
                        <BibtexCodeBlock
                          :source="revision.submittedBibtex || ''"
                          accessible-label="Submitted BibTeX source"
                        />
                      </template>
                      <h4>Laboratory BibTeX</h4>
                      <BibtexCodeBlock
                        :source="revision.canonicalBibtex"
                        accessible-label="Canonical laboratory BibTeX"
                      />
                    </details>
                  </div>
                  <button
                    v-if="canRestore(revision)"
                    type="button"
                    class="button-secondary history-restore"
                    @click="requestRestore(revision.revision)"
                  >
                    Restore
                  </button>

                  <div
                    v-if="pendingRevision === revision.revision"
                    class="history-confirm"
                  >
                    <p>
                      Restore revision {{ revision.revision }} as a new
                      revision?
                    </p>
                    <div>
                      <button
                        type="button"
                        class="button-secondary"
                        :disabled="isRestoring"
                        @click="pendingRevision = null"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        class="button-primary"
                        :disabled="isRestoring"
                        @click="confirmRestore"
                      >
                        {{ isRestoring ? "Restoring…" : "Confirm restore" }}
                      </button>
                    </div>
                  </div>
                </li>
              </ol>
            </div>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>
