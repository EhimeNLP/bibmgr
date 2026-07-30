<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import {
  deleteReference,
  getReference,
  updateReference,
} from "../api/references";
import type { BibtexDiagnostic } from "../types/bibtex";
import type { Reference } from "../types/reference";
import BibtexEditor from "./BibtexEditor.vue";
import BibtexExportPanel from "./BibtexExportPanel.vue";
import BibtexValidationPanel from "./BibtexValidationPanel.vue";
import AppIcon from "./AppIcon.vue";

const props = defineProps<{
  reference: Reference;
  authenticated: boolean;
}>();

const emit = defineEmits<{
  updated: [reference: Reference];
  deleted: [referenceId: string];
  loginRequired: [];
}>();

const isEditOpen = ref(false);
const isDeleteOpen = ref(false);
const isMenuOpen = ref(false);
const isLoadingReference = ref(false);
const isSaving = ref(false);
const isDeleting = ref(false);
const editSource = ref("");
const initialSource = ref("");
const editSourceRevision = ref("");
const editError = ref<string | null>(null);
const editMessage = ref<string | null>(null);
const deleteError = ref<string | null>(null);
const editDiagnostics = reactive<BibtexDiagnostic[]>([]);
const editDialog = ref<HTMLElement | null>(null);
const deleteDialog = ref<HTMLElement | null>(null);
const actionsRoot = ref<HTMLElement | null>(null);
const actionsMenu = ref<HTMLElement | null>(null);
const actionsTrigger = ref<HTMLButtonElement | null>(null);
let loadGeneration = 0;

const canSave = computed(
  () =>
    editSource.value.trim().length > 0 &&
    editSource.value !== initialSource.value &&
    editSourceRevision.value.length > 0 &&
    !isLoadingReference.value &&
    !isSaving.value,
);
const saveLabel = computed(() => {
  if (isSaving.value) return "Saving…";
  return "Save changes";
});

watch(
  () => props.reference.id,
  () => {
    loadGeneration += 1;
    isMenuOpen.value = false;
    isEditOpen.value = false;
    isDeleteOpen.value = false;
    syncBodyLock();
  },
);

onMounted(() => {
  document.addEventListener("pointerdown", onDocumentPointerDown);
});

onBeforeUnmount(() => {
  loadGeneration += 1;
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.body.classList.remove("reference-write-open");
});

async function openEdit() {
  isMenuOpen.value = false;
  if (!props.authenticated) {
    emit("loginRequired");
    return;
  }

  const referenceId = props.reference.id;
  const generation = ++loadGeneration;
  isEditOpen.value = true;
  isLoadingReference.value = true;
  editError.value = null;
  editMessage.value = null;
  replaceDiagnostics([]);
  editSource.value = props.reference.bibtex ?? "";
  initialSource.value = editSource.value;
  editSourceRevision.value = props.reference.sourceRevision ?? "";
  syncBodyLock();
  await nextTick();
  editDialog.value?.focus({ preventScroll: true });

  try {
    const latest = await getReference(referenceId);
    if (
      generation !== loadGeneration ||
      !isEditOpen.value ||
      props.reference.id !== referenceId
    ) {
      return;
    }
    editSource.value = latest.bibtex ?? "";
    initialSource.value = editSource.value;
    editSourceRevision.value = latest.sourceRevision ?? "";
    if (!editSource.value || !editSourceRevision.value) {
      editError.value =
        "The latest stored BibTeX or source revision is unavailable.";
    }
  } catch (error) {
    if (generation !== loadGeneration || !isEditOpen.value) return;
    editError.value = errorText(error, "Could not load the latest reference.");
  } finally {
    if (generation === loadGeneration) isLoadingReference.value = false;
  }
}

async function closeEdit() {
  if (isSaving.value) return;
  loadGeneration += 1;
  isEditOpen.value = false;
  syncBodyLock();
  await nextTick();
  actionsTrigger.value?.focus({ preventScroll: true });
}

async function saveEdit() {
  if (!canSave.value) return;

  const bibtex = editSource.value;
  const sourceRevision = editSourceRevision.value;
  isSaving.value = true;
  editError.value = null;
  editMessage.value = null;

  try {
    const updated = await updateReference(props.reference.id, {
      bibtex,
      source_revision: sourceRevision,
    });
    emit("updated", updated);
    initialSource.value = updated.bibtex ?? bibtex;
    await closeEditAfterSave();
  } catch (error) {
    editError.value = errorText(error, "Could not update the reference.");
  } finally {
    isSaving.value = false;
  }
}

async function closeEditAfterSave() {
  loadGeneration += 1;
  isEditOpen.value = false;
  syncBodyLock();
  await nextTick();
  actionsTrigger.value?.focus({ preventScroll: true });
}

async function requestDelete() {
  isMenuOpen.value = false;
  if (!props.authenticated) {
    emit("loginRequired");
    return;
  }
  isDeleteOpen.value = true;
  deleteError.value = null;
  syncBodyLock();
  await nextTick();
  deleteDialog.value?.focus({ preventScroll: true });
}

async function closeDelete() {
  if (isDeleting.value) return;
  isDeleteOpen.value = false;
  deleteError.value = null;
  syncBodyLock();
  await nextTick();
  actionsTrigger.value?.focus({ preventScroll: true });
}

async function confirmDelete() {
  if (isDeleting.value) return;
  const referenceId = props.reference.id;
  isDeleting.value = true;
  deleteError.value = null;

  try {
    const sourceRevision = props.reference.sourceRevision;
    if (!sourceRevision) {
      deleteError.value =
        "The stored revision is unavailable. Reload the library before deleting.";
      return;
    }
    await deleteReference(referenceId, sourceRevision);
    isDeleteOpen.value = false;
    syncBodyLock();
    emit("deleted", referenceId);
  } catch (error) {
    deleteError.value = errorText(error, "Could not delete the reference.");
  } finally {
    isDeleting.value = false;
  }
}

function replaceDiagnostics(diagnostics: BibtexDiagnostic[]) {
  editDiagnostics.splice(0, editDiagnostics.length, ...diagnostics);
}

function onFixApplied() {
  editError.value = null;
  editMessage.value = "Fix applied. Check BibTeX again to confirm the result.";
}
function errorText(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim()
    ? error.message
    : fallback;
}

function syncBodyLock() {
  document.body.classList.toggle(
    "reference-write-open",
    isEditOpen.value || isDeleteOpen.value,
  );
}

function toggleMenu() {
  isMenuOpen.value = !isMenuOpen.value;
}

async function openMenuFromKeyboard(position: "first" | "last") {
  isMenuOpen.value = true;
  await nextTick();
  const items = menuItems();
  const target = position === "first" ? items[0] : items.at(-1);
  target?.focus({ preventScroll: true });
}

function closeMenu(returnFocus = false) {
  isMenuOpen.value = false;
  if (returnFocus) {
    void nextTick(() => actionsTrigger.value?.focus({ preventScroll: true }));
  }
}

function onMenuKeydown(event: KeyboardEvent) {
  const items = menuItems();
  if (items.length === 0) return;
  const currentIndex = items.findIndex(
    (item) => item === document.activeElement,
  );
  let nextIndex: number | undefined;

  if (event.key === "ArrowDown") {
    nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % items.length;
  } else if (event.key === "ArrowUp") {
    nextIndex =
      currentIndex < 0 ? items.length - 1 : (currentIndex - 1 + items.length) % items.length;
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = items.length - 1;
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeMenu(true);
    return;
  }

  if (nextIndex === undefined) return;
  event.preventDefault();
  items[nextIndex]?.focus({ preventScroll: true });
}

function menuItems() {
  return Array.from(
    actionsMenu.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ??
      [],
  );
}

function onDocumentPointerDown(event: PointerEvent) {
  if (
    isMenuOpen.value &&
    event.target instanceof Node &&
    !actionsRoot.value?.contains(event.target)
  ) {
    isMenuOpen.value = false;
  }
}

function onEditDialogKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeEdit();
    return;
  }
  trapDialogFocus(event, editDialog.value);
}

function onDeleteDialogKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeDelete();
    return;
  }
  trapDialogFocus(event, deleteDialog.value);
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
  <div ref="actionsRoot" class="reference-actions">
    <button
      ref="actionsTrigger"
      type="button"
      class="reference-actions-trigger"
      aria-label="Reference actions"
      aria-haspopup="menu"
      :aria-expanded="isMenuOpen"
      title="Reference actions"
      @click.stop="toggleMenu"
      @keydown.down.prevent="openMenuFromKeyboard('first')"
      @keydown.up.prevent="openMenuFromKeyboard('last')"
    >
      <AppIcon name="three-dots" />
    </button>

    <div
      v-if="isMenuOpen"
      ref="actionsMenu"
      class="reference-actions-menu"
      role="menu"
      aria-label="Reference actions"
      @keydown="onMenuKeydown"
    >
      <button
        type="button"
        class="reference-actions-menu__item reference-action-edit"
        role="menuitem"
        @click="openEdit"
      >
        <AppIcon name="pencil" />
        <span>Edit…</span>
      </button>
      <div class="reference-actions-menu__separator" role="separator" />
      <button
        type="button"
        class="reference-actions-menu__item reference-actions-menu__item--danger reference-action-delete"
        role="menuitem"
        @click="requestDelete"
      >
        <AppIcon name="trash3" />
        <span>Delete…</span>
      </button>
    </div>

    <Teleport v-if="isEditOpen" to="body">
      <div
        class="registration-backdrop reference-edit-backdrop"
        @click.self="closeEdit"
      >
        <section
          ref="editDialog"
          class="registration-sheet reference-edit-sheet"
          role="dialog"
          aria-modal="true"
          aria-labelledby="reference-edit-heading"
          tabindex="-1"
          @keydown="onEditDialogKeydown"
        >
          <header class="registration-sheet__header">
            <div>
              <h2 id="reference-edit-heading">Edit reference</h2>
              <p>The source is preserved and recorded as a new revision.</p>
            </div>
            <button
              type="button"
              class="registration-close"
              aria-label="Close edit reference"
              :disabled="isSaving"
              @click="closeEdit"
            >
              <AppIcon name="x-lg" />
            </button>
          </header>

          <div class="registration-body">
            <p
              v-if="isLoadingReference"
              class="registration-message status-message"
              role="status"
            >
              Loading the latest revision…
            </p>
            <template v-else>
              <label class="field-label" for="reference-edit-bibtex">
                BibTeX entry
                <span>Replace the complete stored entry.</span>
              </label>
              <BibtexEditor
                id="reference-edit-bibtex"
                v-model="editSource"
                accessible-label="Reference BibTeX entry"
                :disabled="isSaving || Boolean(editError && !editSourceRevision)"
                :diagnostics="editDiagnostics"
              />
              <BibtexValidationPanel
                :source="editSource"
                profile="archive"
                :disabled="isSaving || !editSourceRevision"
                @update:source="editSource = $event"
                @update:diagnostics="replaceDiagnostics"
                @fixed="onFixApplied"
              />

              <p class="registration-help">
                Profile checks are advisory. Structural errors and database
                conflicts can block saving; no output profile rewrites the
                BibTeX.
              </p>
              <section
                v-if="editSource.trim()"
                class="registration-output-preview"
                aria-label="Output preview"
              >
                <h3>Output preview</h3>
                <BibtexExportPanel
                  :source="editSource"
                  :citation-key="reference.bibtexKey"
                />
              </section>

              <div class="registration-actions reference-edit-actions">
                <p
                  v-if="editError"
                  class="registration-error status-message"
                  role="alert"
                >
                  {{ editError }}
                </p>
                <p
                  v-else-if="editMessage"
                  class="registration-message status-message"
                  role="status"
                >
                  {{ editMessage }}
                </p>
                <button
                  type="button"
                  class="button-primary"
                  :disabled="!canSave"
                  :aria-busy="isSaving"
                  @click="saveEdit"
                >
                  <span
                    v-if="isSaving"
                    class="button-spinner"
                    aria-hidden="true"
                  />
                  {{ saveLabel }}
                </button>
              </div>
            </template>
          </div>
        </section>
      </div>
    </Teleport>

    <Teleport v-if="isDeleteOpen" to="body">
      <div
        class="auth-backdrop reference-delete-backdrop"
        @click.self="closeDelete"
      >
        <section
          ref="deleteDialog"
          class="auth-sheet confirmation-sheet"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="reference-delete-heading"
          aria-describedby="reference-delete-description"
          tabindex="-1"
          @keydown="onDeleteDialogKeydown"
        >
          <header class="auth-sheet__header">
            <div>
              <h2 id="reference-delete-heading">Delete Reference?</h2>
              <p id="reference-delete-description">
                “{{ reference.title }}” will be removed from the library. You
                can restore it later from History.
              </p>
            </div>
          </header>
          <p
            v-if="deleteError"
            class="registration-error confirmation-error"
            role="alert"
          >
            {{ deleteError }}
          </p>
          <div class="confirmation-actions">
            <button
              type="button"
              class="button-secondary"
              :disabled="isDeleting"
              @click="closeDelete"
            >
              Cancel
            </button>
            <button
              type="button"
              class="button-danger"
              :disabled="isDeleting"
              :aria-busy="isDeleting"
              @click="confirmDelete"
            >
              {{ isDeleting ? "Deleting…" : "Delete" }}
            </button>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>
