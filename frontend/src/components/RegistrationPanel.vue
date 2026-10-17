<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue";
import { registerBibtexToDatabase } from "../api/registration";
import type { BibtexDiagnostic } from "../types/bibtex";
import type {
  Reference,
  RegisterBibtexResult,
} from "../types/reference";
import { bibliographicEntryRanges, countBibliographicEntries } from "../utils/bibtexHighlight";
import BibtexEditor from "./BibtexEditor.vue";
import BibtexExportPanel from "./BibtexExportPanel.vue";
import BibtexValidationPanel from "./BibtexValidationPanel.vue";
import DuplicateReview from "./DuplicateReview.vue";
import DuplicateOverwrite from "./DuplicateOverwrite.vue";
import { DuplicateReviewError, type DuplicateFinding } from "../api/duplicates";
import AppIcon from "./AppIcon.vue";

type RegistrationMode = "manual" | "file";

const MAX_BIB_FILE_SIZE = 2 * 1024 * 1024;

const props = defineProps<{
  authenticated: boolean;
}>();

const emit = defineEmits<{
  registered: [references: Reference[]];
  loginRequired: [];
}>();

const isOpen = ref(false);
const triggerButton = ref<HTMLButtonElement | null>(null);
const dialogPanel = ref<HTMLElement | null>(null);
const manualDuplicateReview = ref<InstanceType<typeof DuplicateReview> | null>(null);
const fileDuplicateReview = ref<InstanceType<typeof DuplicateReview> | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const mode = ref<RegistrationMode>("manual");

const manualBibtex = ref("");
const manualDuplicates = ref<DuplicateFinding[]>([]);
const manualConfirmation = ref<string>();
const isManualRegistering = ref(false);
const manualError = ref<string | null>(null);
const manualMessage = ref<string | null>(null);
const manualDiagnostics = reactive<BibtexDiagnostic[]>([]);

const selectedBibFile = ref<File | null>(null);
const fileBibtex = ref("");
const fileDuplicates = ref<DuplicateFinding[]>([]);
const fileConfirmation = ref<string>();
const overwrite = ref<{ mode: RegistrationMode; finding: DuplicateFinding; original: string; source: string }>();
watch(manualBibtex, () => { manualDuplicates.value = []; manualConfirmation.value = undefined; if (overwrite.value?.mode === "manual") overwrite.value = undefined; }, { flush: "sync" });
watch(fileBibtex, () => { fileDuplicates.value = []; fileConfirmation.value = undefined; if (overwrite.value?.mode === "file") overwrite.value = undefined; }, { flush: "sync" });
const isFileReading = ref(false);
const isFileRegistering = ref(false);
const fileError = ref<string | null>(null);
const fileMessage = ref<string | null>(null);
const fileDiagnostics = reactive<BibtexDiagnostic[]>([]);

const canRegisterManual = computed(
  () => manualBibtex.value.trim().length > 0 && !isManualRegistering.value,
);
const fileEntryCount = computed(() => countBibliographicEntries(fileBibtex.value));
const canRegisterFile = computed(
  () =>
    Boolean(selectedBibFile.value) &&
    fileBibtex.value.trim().length > 0 &&
    !isFileReading.value &&
    !isFileRegistering.value,
);
const selectedBibFileName = computed(
  () => selectedBibFile.value?.name ?? "No .bib file selected",
);
const fileEntryCountLabel = computed(() =>
  fileEntryCount.value === 1
    ? "1 entry detected."
    : `${fileEntryCount.value} entries detected.`,
);
const fileRegistrationLabel = computed(() => {
  if (isFileRegistering.value) return overwrite.value ? "Overwriting…" : "Registering…";
  if (fileEntryCount.value === 0) return "Register file";
  return fileEntryCount.value === 1
    ? "Register 1 reference"
    : `Register ${fileEntryCount.value} references`;
});
const manualRegistrationLabel = computed(() => {
  if (isManualRegistering.value) return overwrite.value ? "Overwriting…" : "Registering…";
  return "Register BibTeX";
});

onBeforeUnmount(() => {
  document.body.classList.remove("registration-open");
});

async function openRegistration() {
  if (!props.authenticated) {
    emit("loginRequired");
    return;
  }
  isOpen.value = true;
  document.body.classList.add("registration-open");
  await nextTick();
  dialogPanel.value?.focus({ preventScroll: true });
}

async function closeRegistration() {
  if (isManualRegistering.value || isFileRegistering.value) return;
  isOpen.value = false;
  document.body.classList.remove("registration-open");
  await nextTick();
  triggerButton.value?.focus({ preventScroll: true });
}

function onDialogKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeRegistration();
    return;
  }

  if (event.key !== "Tab") return;

  const focusable = Array.from(
    dialogPanel.value?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ) ?? [],
  ).filter((element) => element.getClientRects().length > 0);

  const first = focusable[0];
  const last = focusable.at(-1);
  if (!first || !last) return;

  if (
    event.shiftKey &&
    (document.activeElement === first || document.activeElement === dialogPanel.value)
  ) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function selectMode(nextMode: RegistrationMode, moveFocus = false) {
  if (isManualRegistering.value || isFileRegistering.value) return;
  overwrite.value = undefined;
  mode.value = nextMode;

  if (moveFocus) {
    void nextTick(() => {
      document.getElementById(`registration-tab-${nextMode}`)?.focus();
    });
  }
}

function removeDuplicateEntries(target: RegistrationMode, indices: number[], replacement?: DuplicateFinding) {
  const source = target === "manual" ? manualBibtex : fileBibtex;
  const findings = target === "manual" ? manualDuplicates : fileDuplicates;
  if (target === "manual" ? isManualRegistering.value : isFileRegistering.value) return;
  const ranges = bibliographicEntryRanges(source.value);
  const allowed = new Set(findings.value.map(finding => finding.incoming_index));
  if (replacement && findings.value.includes(replacement) && !replacement.existing) allowed.add(replacement.candidate_index);
  const removed = new Set(indices.filter(index => allowed.has(index) && ranges[index]));
  if (!removed.size) return;
  const reindex = (index: number) => index - [...removed].filter(value => value < index).length;
  const remaining = findings.value
    .filter(finding => !removed.has(finding.incoming_index) && (finding.existing || !removed.has(finding.candidate_index)))
    .map(finding => ({ ...finding, incoming_index: reindex(finding.incoming_index),
      candidate_index: finding.existing ? finding.candidate_index : reindex(finding.candidate_index) }));
  let updated = source.value;
  for (const index of [...removed].sort((a, b) => b - a)) {
    const range = ranges[index]!;
    updated = updated.slice(0, range.start) + updated.slice(range.end);
  }
  source.value = updated;
  findings.value = remaining;
  const message = `${removed.size === 1 ? "1 entry" : `${removed.size} entries`} removed from the input. Review and register the remaining entries.`;
  if (target === "manual") {
    manualError.value = null;
    manualMessage.value = message;
    replaceDiagnostics(manualDiagnostics, []);
  } else {
    fileError.value = null;
    fileMessage.value = message;
    replaceDiagnostics(fileDiagnostics, []);
  }
}

function beginOverwrite(target: RegistrationMode, finding: DuplicateFinding) {
  if (isManualRegistering.value || isFileRegistering.value) return;
  const original = target === "manual" ? manualBibtex.value : fileBibtex.value;
  const findings = target === "manual" ? manualDuplicates.value : fileDuplicates.value;
  if (!findings.includes(finding)) return;
  if (!finding.existing) {
    removeDuplicateEntries(target, [finding.candidate_index], finding);
    return;
  }
  const ranges = bibliographicEntryRanges(original);
  if (!finding.reference_id || !ranges[finding.incoming_index]) return;
  // Keep string definitions, preambles, and comments needed by the selected entry.
  let source = original;
  for (let index = ranges.length - 1; index >= 0; index -= 1) {
    if (index === finding.incoming_index) continue;
    const range = ranges[index]!;
    source = source.slice(0, range.start) + source.slice(range.end);
  }
  overwrite.value = { mode: target, finding, original, source };
  if (target === "manual") manualError.value = null;
  else fileError.value = null;
}

function finishOverwrite(reference: Reference) {
  const selected = overwrite.value;
  if (!selected) return;
  const source = selected.mode === "manual" ? manualBibtex : fileBibtex;
  if (source.value === selected.original) {
    removeDuplicateEntries(selected.mode, [selected.finding.incoming_index]);
    const message = countBibliographicEntries(source.value)
      ? "Reference overwritten. Review and register the remaining entries."
      : "Reference overwritten.";
    if (selected.mode === "manual") {
      manualDuplicates.value = []; manualMessage.value = message;
    } else {
      fileDuplicates.value = []; fileMessage.value = message;
    }
  }
  overwrite.value = undefined;
  emit("registered", [reference]);
  void nextTick(() => document.getElementById(selected.mode === "manual" ? "manual-bibtex" : "file-bibtex-preview")?.focus());
}

async function registerManualBibtex(confirmed = false) {
  if (!manualBibtex.value.trim() || isManualRegistering.value) return;
  overwrite.value = undefined;

  const bibtex = manualBibtex.value;
  isManualRegistering.value = true;
  manualError.value = null;
  manualMessage.value = null;

  try {
    const result = await registerBibtexToDatabase({
      bibtex,
      source: "manual",
      ...(confirmed && manualConfirmation.value ? { duplicate_confirmation: manualConfirmation.value } : {}),
    });
    manualBibtex.value = "";
    replaceDiagnostics(manualDiagnostics, []);
    manualDuplicates.value = result.duplicateWarnings ?? [];
    manualConfirmation.value = undefined;
    manualMessage.value = "Registered.";
    emitRegisteredReferences(result);
    void manualDuplicateReview.value?.reveal();
  } catch (error) {
    if (error instanceof DuplicateReviewError) {
      manualDuplicates.value = error.findings;
      manualConfirmation.value = error.confirmationToken;
      void manualDuplicateReview.value?.reveal();
    }
    manualError.value =
      error instanceof Error ? error.message : "Failed to register BibTeX.";
  } finally {
    isManualRegistering.value = false;
  }
}

async function onBibFileChange(event: Event) {
  if (isFileRegistering.value) return;
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];

  selectedBibFile.value = null;
  fileBibtex.value = "";
  replaceDiagnostics(fileDiagnostics, []);
  fileError.value = null;
  fileMessage.value = null;

  if (!file) return;

  if (!file.name.toLowerCase().endsWith(".bib")) {
    failFileSelection("Choose a file with the .bib extension.", input);
    return;
  }

  if (file.size > MAX_BIB_FILE_SIZE) {
    failFileSelection("The .bib file must be 2 MB or smaller.", input);
    return;
  }

  selectedBibFile.value = file;
  isFileReading.value = true;
  fileMessage.value = `Reading ${file.name}…`;

  try {
    const bibtex = (await file.text()).replace(/^\uFEFF/, "");
    if (!bibtex.trim()) {
      failFileSelection("The selected .bib file is empty.", input);
      return;
    }

    fileBibtex.value = bibtex;
    fileMessage.value = `${file.name} is ready.`;
  } catch (error) {
    failFileSelection(
      error instanceof Error
        ? `Could not read ${file.name}: ${error.message}`
        : `Could not read ${file.name}.`,
      input,
    );
  } finally {
    isFileReading.value = false;
  }
}

async function registerFileBibtex(confirmed = false) {
  if (!selectedBibFile.value || !fileBibtex.value.trim() || isFileRegistering.value) return;
  overwrite.value = undefined;

  const fileName = selectedBibFile.value.name;
  const bibtex = fileBibtex.value;
  isFileRegistering.value = true;
  fileError.value = null;
  fileMessage.value = null;

  try {
    const result = await registerBibtexToDatabase({
      bibtex,
      source: "file",
      ...(confirmed && fileConfirmation.value ? { duplicate_confirmation: fileConfirmation.value } : {}),
    });
    selectedBibFile.value = null;
    fileBibtex.value = "";
    replaceDiagnostics(fileDiagnostics, []);
    resetFileInput();
    fileDuplicates.value = result.duplicateWarnings ?? [];
    fileConfirmation.value = undefined;
    fileMessage.value = `${fileName} was registered.`;
    emitRegisteredReferences(result);
    void fileDuplicateReview.value?.reveal();
  } catch (error) {
    if (error instanceof DuplicateReviewError) {
      fileDuplicates.value = error.findings;
      fileConfirmation.value = error.confirmationToken;
      void fileDuplicateReview.value?.reveal();
    }
    fileError.value =
      error instanceof Error ? error.message : "Failed to register BibTeX.";
  } finally {
    isFileRegistering.value = false;
  }
}

function failFileSelection(message: string, input: HTMLInputElement) {
  selectedBibFile.value = null;
  fileBibtex.value = "";
  replaceDiagnostics(fileDiagnostics, []);
  fileMessage.value = null;
  fileError.value = message;
  input.value = "";
}

function resetFileInput() {
  if (fileInput.value) fileInput.value.value = "";
}

function emitRegisteredReferences(result: RegisterBibtexResult) {
  const references =
    result.references?.length ? result.references : [result.reference];
  emit("registered", references);
}

function replaceDiagnostics(
  target: BibtexDiagnostic[],
  diagnostics: BibtexDiagnostic[],
) {
  target.splice(0, target.length, ...diagnostics);
}

function onManualDiagnostics(diagnostics: BibtexDiagnostic[]) {
  replaceDiagnostics(manualDiagnostics, diagnostics);
}

function onFileDiagnostics(diagnostics: BibtexDiagnostic[]) {
  replaceDiagnostics(fileDiagnostics, diagnostics);
}

function onManualFixApplied() {
  manualError.value = null;
  manualMessage.value = "Fix applied. Check BibTeX again to confirm the result.";
}

function onFileFixApplied() {
  fileError.value = null;
  fileMessage.value = "Fix applied. Check BibTeX again to confirm the result.";
}
</script>

<template>
  <div class="registration-panel">
    <button
      ref="triggerButton"
      type="button"
      class="registration-trigger"
      aria-label="Add reference"
      aria-haspopup="dialog"
      :aria-expanded="isOpen"
      :title="authenticated ? undefined : 'Log in to add references'"
      @click="openRegistration"
    >
      <AppIcon name="plus-lg" />
      <span>Add reference</span>
    </button>

    <Teleport v-if="isOpen" to="body">
      <div
        class="registration-backdrop"
        @click.self="closeRegistration"
      >
        <section
          ref="dialogPanel"
          class="registration-sheet"
          role="dialog"
          aria-modal="true"
          aria-labelledby="registration-heading"
          tabindex="-1"
          @keydown="onDialogKeydown"
        >
          <header class="registration-sheet__header">
            <div>
              <h2 id="registration-heading">Add references</h2>
              <p>Paste a BibTeX entry or choose a .bib file.</p>
            </div>
            <button
              type="button"
              class="registration-close"
              aria-label="Close add references"
              @click="closeRegistration"
            >
              <AppIcon name="x-lg" />
            </button>
          </header>

          <div class="registration-header">
            <div class="mode-tabs" role="tablist" aria-label="Registration mode">
              <button
                id="registration-tab-manual"
                type="button"
                role="tab"
                :class="{ active: mode === 'manual' }"
                :aria-selected="mode === 'manual'"
                aria-controls="registration-panel-manual"
                :tabindex="mode === 'manual' ? 0 : -1"
                @click="selectMode('manual')"
                @keydown.right.prevent="selectMode('file', true)"
                @keydown.left.prevent="selectMode('file', true)"
                @keydown.home.prevent="selectMode('manual', true)"
                @keydown.end.prevent="selectMode('file', true)"
              >
                Manual entry
              </button>
              <button
                id="registration-tab-file"
                type="button"
                role="tab"
                :class="{ active: mode === 'file' }"
                :aria-selected="mode === 'file'"
                aria-controls="registration-panel-file"
                :tabindex="mode === 'file' ? 0 : -1"
                @click="selectMode('file')"
                @keydown.left.prevent="selectMode('manual', true)"
                @keydown.right.prevent="selectMode('manual', true)"
                @keydown.home.prevent="selectMode('manual', true)"
                @keydown.end.prevent="selectMode('file', true)"
              >
                BibTeX file
              </button>
            </div>
          </div>

          <div
            v-if="mode === 'manual'"
            id="registration-panel-manual"
            class="registration-body"
            role="tabpanel"
            aria-labelledby="registration-tab-manual"
          >
            <label class="field-label" for="manual-bibtex">
              BibTeX entry
              <span>Paste one complete entry below.</span>
            </label>
            <BibtexEditor
              id="manual-bibtex"
              v-model="manualBibtex"
              accessible-label="BibTeX entry"
              placeholder="@article{...}"
              :disabled="isManualRegistering"
              :diagnostics="manualDiagnostics"
            />
            <BibtexValidationPanel
              :source="manualBibtex"
              profile="archive"
              safe-fixes-on-export
              :disabled="isManualRegistering"
              @update:source="manualBibtex = $event"
              @update:diagnostics="onManualDiagnostics"
              @fixed="onManualFixApplied"
            />

            <p class="registration-help">
              The source is stored exactly as submitted. Profile checks are
              advisory; structural errors and database conflicts can still
              reject registration.
            </p>
            <section
              v-if="manualBibtex.trim()"
              class="registration-output-preview"
              aria-label="Output preview"
            >
              <h3>Output preview</h3>
              <BibtexExportPanel :source="manualBibtex" />
            </section>

            <DuplicateReview
              ref="manualDuplicateReview"
              :findings="manualDuplicates"
              :can-remove="Boolean(manualBibtex.trim())"
              :can-overwrite="Boolean(manualBibtex.trim())"
              :confirmation-token="manualConfirmation"
              :busy="isManualRegistering"
              @remove="removeDuplicateEntries('manual', $event)"
              @overwrite="beginOverwrite('manual', $event)"
              @confirm="registerManualBibtex(true)"
            />
            <DuplicateOverwrite
              v-if="overwrite?.mode === 'manual'"
              key="manual-overwrite"
              :reference-id="overwrite.finding.reference_id!"
              :source="overwrite.source"
              @busy="isManualRegistering = $event"
              @saved="finishOverwrite"
              @cancel="overwrite = undefined"
            />
            <div class="registration-actions">
              <p
                v-if="manualError"
                class="registration-error status-message"
                role="alert"
              >
                {{ manualError }}
              </p>
              <p
                v-else-if="manualMessage"
                class="registration-message status-message"
                role="status"
              >
                {{ manualMessage }}
              </p>
              <button
                type="button"
                class="button-primary"
                :disabled="!canRegisterManual"
                :aria-busy="isManualRegistering"
                @click="registerManualBibtex()"
              >
                <span
                  v-if="isManualRegistering"
                  class="button-spinner"
                  aria-hidden="true"
                />
                {{ manualRegistrationLabel }}
              </button>
            </div>
          </div>

          <div
            v-if="mode === 'file'"
            id="registration-panel-file"
            class="registration-body"
            role="tabpanel"
            aria-labelledby="registration-tab-file"
          >
            <label class="file-picker">
              <input
                id="bibtex-file"
                ref="fileInput"
                type="file"
                accept=".bib,text/x-bibtex,application/x-bibtex,text/plain"
                :disabled="isFileReading || isFileRegistering"
                @change="onBibFileChange"
              />
              <span class="file-picker__icon" aria-hidden="true">
                <AppIcon name="file-earmark-text" />
              </span>
              <span class="file-picker__copy">
                <strong>{{ selectedBibFile ? "BibTeX file selected" : "Choose a .bib file" }}</strong>
                <span>{{ selectedBibFileName }}</span>
              </span>
              <span class="file-picker__action">Browse</span>
            </label>
            <p id="bibtex-file-help" class="registration-help">
              One or more entries, up to 2 MB. You can review them before registering.
            </p>

            <p
              v-if="fileError"
              class="registration-error status-message"
              role="alert"
            >
              {{ fileError }}
            </p>
            <p
              v-else-if="fileMessage"
              class="registration-message status-message"
              role="status"
            >
              {{ fileMessage }}
              <span v-if="fileBibtex">{{ fileEntryCountLabel }}</span>
            </p>

            <template v-if="fileBibtex">
              <label class="field-label" for="file-bibtex-preview">
                File contents
                <span>Review or edit before registering.</span>
              </label>
              <BibtexEditor
                id="file-bibtex-preview"
                v-model="fileBibtex"
                accessible-label="BibTeX file contents"
                :disabled="isFileRegistering"
                :diagnostics="fileDiagnostics"
              />
              <BibtexValidationPanel
                :source="fileBibtex"
                profile="archive"
                safe-fixes-on-export
                :disabled="isFileRegistering"
                @update:source="fileBibtex = $event"
                @update:diagnostics="onFileDiagnostics"
                @fixed="onFileFixApplied"
              />
              <p class="registration-help">
                Each entry is stored without applying an output profile.
                Structural errors and database conflicts can still reject the
                batch.
              </p>
              <section
                class="registration-output-preview"
                aria-label="Output preview"
              >
                <h3>Output preview</h3>
                <BibtexExportPanel :source="fileBibtex" />
              </section>
            </template>

            <DuplicateReview
              ref="fileDuplicateReview"
              :findings="fileDuplicates"
              :can-remove="Boolean(fileBibtex.trim())"
              :can-overwrite="Boolean(fileBibtex.trim())"
              :confirmation-token="fileConfirmation"
              :busy="isFileRegistering"
              @remove="removeDuplicateEntries('file', $event)"
              @overwrite="beginOverwrite('file', $event)"
              @confirm="registerFileBibtex(true)"
            />
            <DuplicateOverwrite
              v-if="overwrite?.mode === 'file'"
              key="file-overwrite"
              :reference-id="overwrite.finding.reference_id!"
              :source="overwrite.source"
              @busy="isFileRegistering = $event"
              @saved="finishOverwrite"
              @cancel="overwrite = undefined"
            />
            <div class="registration-actions registration-actions--file">
              <button
                type="button"
                class="button-primary"
                :disabled="!canRegisterFile"
                :aria-busy="isFileRegistering"
                @click="registerFileBibtex()"
              >
                <span
                  v-if="isFileRegistering"
                  class="button-spinner"
                  aria-hidden="true"
                />
                {{ fileRegistrationLabel }}
              </button>
            </div>
          </div>

        </section>
      </div>
    </Teleport>
  </div>
</template>
