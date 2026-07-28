<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref } from "vue";
import { registerBibtexToDatabase } from "../api/registration";
import type { BibtexDiagnostic } from "../types/bibtex";
import type {
  Reference,
  RegisterBibtexResult,
} from "../types/reference";
import { countBibliographicEntries } from "../utils/bibtexHighlight";
import BibtexEditor from "./BibtexEditor.vue";
import BibtexExportPanel from "./BibtexExportPanel.vue";
import BibtexValidationPanel from "./BibtexValidationPanel.vue";

type RegistrationMode = "manual" | "file";

const MAX_BIB_FILE_SIZE = 2 * 1024 * 1024;

const props = defineProps<{
  authenticated: boolean;
}>();

const emit = defineEmits<{
  registered: [reference: Reference];
  loginRequired: [];
}>();

const isOpen = ref(false);
const triggerButton = ref<HTMLButtonElement | null>(null);
const dialogPanel = ref<HTMLElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const mode = ref<RegistrationMode>("manual");

const manualBibtex = ref("");
const isManualRegistering = ref(false);
const manualError = ref<string | null>(null);
const manualMessage = ref<string | null>(null);
const manualDiagnostics = reactive<BibtexDiagnostic[]>([]);

const selectedBibFile = ref<File | null>(null);
const fileBibtex = ref("");
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
  if (isFileRegistering.value) return "Registering…";
  if (fileEntryCount.value === 0) return "Register file";
  return fileEntryCount.value === 1
    ? "Register 1 reference"
    : `Register ${fileEntryCount.value} references`;
});
const manualRegistrationLabel = computed(() => {
  if (isManualRegistering.value) return "Registering…";
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
  mode.value = nextMode;

  if (moveFocus) {
    void nextTick(() => {
      document.getElementById(`registration-tab-${nextMode}`)?.focus();
    });
  }
}

async function registerManualBibtex() {
  if (!manualBibtex.value.trim()) return;

  const bibtex = manualBibtex.value;
  isManualRegistering.value = true;
  manualError.value = null;
  manualMessage.value = null;

  try {
    const result = await registerBibtexToDatabase({
      bibtex,
      source: "manual",
    });
    manualBibtex.value = "";
    replaceDiagnostics(manualDiagnostics, []);
    manualMessage.value = "Registered.";
    emitRegisteredReferences(result);
  } catch (error) {
    manualError.value =
      error instanceof Error ? error.message : "Failed to register BibTeX.";
  } finally {
    isManualRegistering.value = false;
  }
}

async function onBibFileChange(event: Event) {
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

async function registerFileBibtex() {
  if (!selectedBibFile.value || !fileBibtex.value.trim()) return;

  const fileName = selectedBibFile.value.name;
  const bibtex = fileBibtex.value;
  isFileRegistering.value = true;
  fileError.value = null;
  fileMessage.value = null;

  try {
    const result = await registerBibtexToDatabase({
      bibtex,
      source: "file",
    });
    selectedBibFile.value = null;
    fileBibtex.value = "";
    replaceDiagnostics(fileDiagnostics, []);
    resetFileInput();
    fileMessage.value = `${fileName} was registered.`;
    emitRegisteredReferences(result);
  } catch (error) {
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
  for (const reference of references) {
    emit("registered", reference);
  }
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
      <svg aria-hidden="true" viewBox="0 0 18 18" fill="none">
        <path d="M9 3.5v11M3.5 9h11" />
      </svg>
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
              <svg aria-hidden="true" viewBox="0 0 18 18" fill="none">
                <path d="m5 5 8 8M13 5l-8 8" />
              </svg>
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
                @click="registerManualBibtex"
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
                <svg viewBox="0 0 20 20" fill="none">
                  <path d="M11.5 2.5H5A1.5 1.5 0 0 0 3.5 4v12A1.5 1.5 0 0 0 5 17.5h10a1.5 1.5 0 0 0 1.5-1.5V7.5l-5-5Z" />
                  <path d="M11.5 2.5v5h5M7 12.5h6M7 9.5h2.5" />
                </svg>
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

            <div class="registration-actions registration-actions--file">
              <button
                type="button"
                class="button-primary"
                :disabled="!canRegisterFile"
                :aria-busy="isFileRegistering"
                @click="registerFileBibtex"
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
