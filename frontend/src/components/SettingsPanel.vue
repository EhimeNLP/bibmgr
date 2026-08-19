<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import {
  deleteExportProfile,
  deleteVenue,
  getApplicationConfiguration,
  getConfigurationHistory,
  updateExportProfile,
  updateVenue,
} from "../api/configuration";
import type {
  ApplicationConfiguration,
  ExportProfileData,
  ConfigurationHistoryAction,
  ConfigurationHistoryEvent,
  ConfigurationKind,
  VenueData,
  VenueKind,
} from "../types/configuration";
import { exportProfileErrors } from "../utils/exportProfile";
import AppIcon from "./AppIcon.vue";
import ExportProfileEditor from "./ExportProfileEditor.vue";
import UnifiedDiff from "./UnifiedDiff.vue";

const props = defineProps<{ authenticated: boolean }>();
const emit = defineEmits<{
  changed: [];
  loginRequired: [];
}>();

const isOpen = ref(false);
const isLoading = ref(false);
const isSaving = ref(false);
const isDeleting = ref(false);
const isLoadingHistory = ref(false);
const activeSection = ref<"profiles" | "venues">("profiles");
const historyMode = ref(false);
const historyItems = ref<ConfigurationHistoryEvent[]>([]);
const historyTotal = ref(0);
const historyError = ref<string | null>(null);
const createMode = ref<"profile" | "venue" | null>(null);
const newConfigurationKey = ref("");
const configuration = ref<ApplicationConfiguration | null>(null);
const selectedProfileId = ref<string | null>(null);
const selectedVenueId = ref<string | null>(null);
const profileDraft = ref<ExportProfileData | null>(null);
const venueDraft = ref<VenueData | null>(null);
const errorMessage = ref<string | null>(null);
const statusMessage = ref<string | null>(null);
const pendingDeletion = ref<{
  section: "profiles" | "venues";
  key: string;
  name: string;
  builtIn: boolean;
} | null>(null);
const dialog = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const confirmationAction = ref<HTMLButtonElement | null>(null);
let loadGeneration = 0;
let historyGeneration = 0;
const venueKinds: VenueKind[] = [
  "conference",
  "journal",
  "workshop",
  "book-series",
  "other",
];

const selectedProfile = computed(
  () =>
    configuration.value?.export_profiles.find(
      (entry) => entry.key === selectedProfileId.value,
    ) ?? null,
);
const selectedVenue = computed(
  () =>
    configuration.value?.venues.find(
      (entry) => entry.key === selectedVenueId.value,
    ) ?? null,
);
const isBusy = computed(() => isSaving.value || isDeleting.value);
const profileDraftId = computed(() => {
  if (createMode.value === "profile") {
    return validConfigurationKey(newConfigurationKey.value, "profile") ?? "";
  }
  return selectedProfile.value?.key ?? "";
});
const profileDraftData = computed(() => {
  const key = profileDraftId.value;
  return key && profileDraft.value
    ? { ...cloneData(profileDraft.value), profile: key }
    : null;
});
const normalizedVenueDraft = computed(() => {
  const key =
    createMode.value === "venue"
      ? validConfigurationKey(newConfigurationKey.value, "venue")
      : selectedVenue.value?.key;
  return key && venueDraft.value
    ? normalizeVenueData(venueDraft.value, key)
    : null;
});
const canSaveProfile = computed(() => {
  const data = profileDraftData.value;
  if (!data || exportProfileErrors(data).length > 0) return false;
  if (createMode.value === "profile") return true;
  return Boolean(
    selectedProfile.value &&
      !sameData(data, selectedProfile.value.data),
  );
});
const canSaveVenue = computed(() => {
  const data = normalizedVenueDraft.value;
  if (!data || !data.full_name || !data.short_name) return false;
  if (createMode.value === "venue") return true;
  return Boolean(
    selectedVenue.value && !sameData(data, selectedVenue.value.data),
  );
});

watch(
  () => props.authenticated,
  (authenticated) => {
    if (!authenticated && isOpen.value) void closeSettings();
  },
);

onBeforeUnmount(() => {
  loadGeneration += 1;
  historyGeneration += 1;
  document.body.classList.remove("settings-open");
  document.getElementById("app")?.removeAttribute("inert");
});

async function openSettings() {
  if (!props.authenticated) {
    emit("loginRequired");
    return;
  }
  isOpen.value = true;
  document.body.classList.add("settings-open");
  document.getElementById("app")?.setAttribute("inert", "");
  await nextTick();
  dialog.value?.focus({ preventScroll: true });
  await loadConfiguration();
}

async function closeSettings() {
  if (isBusy.value) return;
  loadGeneration += 1;
  historyGeneration += 1;
  historyMode.value = false;
  isLoadingHistory.value = false;
  isOpen.value = false;
  document.body.classList.remove("settings-open");
  document.getElementById("app")?.removeAttribute("inert");
  await nextTick();
  trigger.value?.focus({ preventScroll: true });
}

async function loadConfiguration(preferred?: {
  section: "profiles" | "venues";
  key: string;
}) {
  const generation = ++loadGeneration;
  isLoading.value = true;
  errorMessage.value = null;
  statusMessage.value = null;
  try {
    const loaded = await getApplicationConfiguration();
    if (generation !== loadGeneration || !isOpen.value) return;
    configuration.value = loaded;
    historyMode.value = false;
    createMode.value = null;
    newConfigurationKey.value = "";
    pendingDeletion.value = null;
    selectedProfileId.value =
      preferred?.section === "profiles"
        ? preferred.key
        : selectedProfileId.value;
    selectedVenueId.value =
      preferred?.section === "venues"
        ? preferred.key
        : selectedVenueId.value;
    if (
      !loaded.export_profiles.some(
        (entry) => entry.key === selectedProfileId.value,
      )
    ) {
      selectedProfileId.value = loaded.export_profiles[0]?.key ?? null;
    }
    if (
      !loaded.venues.some((entry) => entry.key === selectedVenueId.value)
    ) {
      selectedVenueId.value = loaded.venues[0]?.key ?? null;
    }
    syncProfileDraft();
    syncVenueDraft();
  } catch (error) {
    if (generation !== loadGeneration || !isOpen.value) return;
    errorMessage.value = errorText(error, "Could not load settings.");
  } finally {
    if (generation === loadGeneration) isLoading.value = false;
  }
}

function selectProfile(key: string) {
  closeHistory();
  createMode.value = null;
  pendingDeletion.value = null;
  selectedProfileId.value = key;
  errorMessage.value = null;
  statusMessage.value = null;
  syncProfileDraft();
}

function selectVenue(key: string) {
  closeHistory();
  createMode.value = null;
  pendingDeletion.value = null;
  selectedVenueId.value = key;
  errorMessage.value = null;
  statusMessage.value = null;
  syncVenueDraft();
}

function syncProfileDraft() {
  profileDraft.value = selectedProfile.value
    ? cloneData(selectedProfile.value.data)
    : null;
}

function syncVenueDraft() {
  venueDraft.value = selectedVenue.value
    ? cloneData(selectedVenue.value.data)
    : null;
}

async function saveProfile() {
  const creating = createMode.value === "profile";
  const key = creating
    ? configurationKey(newConfigurationKey.value, "profile")
    : selectedProfile.value?.key;
  const entry = creating
    ? key
      ? { key, revision: 0 }
      : null
    : selectedProfile.value;
  if (!entry || isBusy.value) return;
  errorMessage.value = null;
  statusMessage.value = null;
  const data =
    profileDraft.value
      ? { ...cloneData(profileDraft.value), profile: entry.key }
      : null;
  if (!data) {
    errorMessage.value = "Profile definition is unavailable.";
    return;
  }
  const profileErrors = exportProfileErrors(data);
  if (profileErrors.length > 0) {
    errorMessage.value = profileErrors[0];
    return;
  }
  if (!creating && sameData(data, selectedProfile.value?.data)) {
    return;
  }
  isSaving.value = true;
  try {
    await updateExportProfile(entry, data);
    emit("changed");
    await loadConfiguration({ section: "profiles", key: entry.key });
    statusMessage.value = `${entry.key} was saved.`;
  } catch (error) {
    errorMessage.value = errorText(error, "Could not save the profile.");
  } finally {
    isSaving.value = false;
  }
}

async function saveVenue() {
  const creating = createMode.value === "venue";
  const key = creating
    ? configurationKey(newConfigurationKey.value, "venue")
    : selectedVenue.value?.key;
  const entry = creating
    ? key
      ? { key, revision: 0 }
      : null
    : selectedVenue.value;
  const data =
    key && venueDraft.value
      ? normalizeVenueData(venueDraft.value, key)
      : null;
  if (!entry || !data || isBusy.value) return;
  errorMessage.value = null;
  statusMessage.value = null;
  if (!creating && sameData(data, selectedVenue.value?.data)) return;
  isSaving.value = true;
  try {
    await updateVenue(entry, data);
    emit("changed");
    await loadConfiguration({ section: "venues", key: entry.key });
    statusMessage.value = `${entry.key} was saved.`;
  } catch (error) {
    errorMessage.value = errorText(error, "Could not save the venue.");
  } finally {
    isSaving.value = false;
  }
}

function aliasesText(data: VenueData) {
  return data.aliases.join("\n");
}

function updateAliases(event: Event) {
  if (!venueDraft.value || !(event.target instanceof HTMLTextAreaElement)) return;
  venueDraft.value.aliases = event.target.value.split("\n");
}

function selectSection(section: "profiles" | "venues") {
  closeHistory();
  activeSection.value = section;
  createMode.value = null;
  newConfigurationKey.value = "";
  pendingDeletion.value = null;
  errorMessage.value = null;
  statusMessage.value = null;
}

function startAddingProfile() {
  closeHistory();
  const base =
    selectedProfile.value?.data ??
    configuration.value?.export_profiles[0]?.data;
  if (!base) return;
  createMode.value = "profile";
  pendingDeletion.value = null;
  newConfigurationKey.value = "";
  profileDraft.value = {
    ...cloneData(base),
    profile: "",
    display_name: `${base.display_name} Copy`,
  };
  errorMessage.value = null;
  statusMessage.value = null;
}

function startAddingVenue() {
  closeHistory();
  createMode.value = "venue";
  pendingDeletion.value = null;
  newConfigurationKey.value = "";
  venueDraft.value = {
    id: "",
    full_name: "",
    short_name: "",
    aliases: [],
    kind: "conference",
  };
  errorMessage.value = null;
  statusMessage.value = null;
}

function cancelAddition() {
  createMode.value = null;
  newConfigurationKey.value = "";
  syncProfileDraft();
  syncVenueDraft();
  errorMessage.value = null;
  statusMessage.value = null;
}

async function requestProfileDeletion() {
  const entry = selectedProfile.value;
  if (!entry || entry.revision === 0) return;
  pendingDeletion.value = {
    section: "profiles",
    key: entry.key,
    name: entry.data.display_name,
    builtIn: entry.built_in,
  };
  await nextTick();
  confirmationAction.value?.focus();
}

async function requestVenueDeletion() {
  const entry = selectedVenue.value;
  if (!entry || entry.revision === 0) return;
  pendingDeletion.value = {
    section: "venues",
    key: entry.key,
    name: entry.data.short_name,
    builtIn: entry.built_in,
  };
  await nextTick();
  confirmationAction.value?.focus();
}

async function confirmDeletion() {
  const deletion = pendingDeletion.value;
  if (!deletion || isBusy.value) return;
  const entry =
    deletion.section === "profiles"
      ? selectedProfile.value
      : selectedVenue.value;
  if (!entry || entry.key !== deletion.key) return;
  errorMessage.value = null;
  statusMessage.value = null;
  isDeleting.value = true;
  try {
    const result =
      deletion.section === "profiles"
        ? await deleteExportProfile(entry)
        : await deleteVenue(entry);
    emit("changed");
    await loadConfiguration();
    statusMessage.value = result.reset
      ? `${deletion.key} was restored to its built-in definition.`
      : `${deletion.key} was deleted.`;
  } catch (error) {
    errorMessage.value = errorText(error, "Could not remove the setting.");
  } finally {
    isDeleting.value = false;
  }
}

function configurationKey(
  value: string,
  section: "profile" | "venue",
) {
  const key = value.trim();
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(key)) {
    errorMessage.value =
      "ID must use lowercase letters, numbers, and single hyphens.";
    return null;
  }
  if (!validConfigurationKey(key, section)) {
    errorMessage.value = `The ID ${key} is already in use.`;
    return null;
  }
  return key;
}

function validConfigurationKey(
  value: string,
  section: "profile" | "venue",
) {
  const key = value.trim();
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(key)) return null;
  const alreadyExists =
    section === "profile"
      ? configuration.value?.export_profiles.some((entry) => entry.key === key)
      : configuration.value?.venues.some((entry) => entry.key === key);
  return alreadyExists ? null : key;
}

function normalizeVenueData(data: VenueData, key: string): VenueData {
  return {
    ...cloneData(data),
    id: key,
    full_name: data.full_name.trim(),
    short_name: data.short_name.trim(),
    aliases: data.aliases.map((alias) => alias.trim()).filter(Boolean),
  };
}

function sameData(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameData(value, right[index]))
    );
  }
  if (!isRecord(left) || !isRecord(right)) return false;
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return (
    leftKeys.length === rightKeys.length &&
    leftKeys.every(
      (key, index) =>
        key === rightKeys[index] && sameData(left[key], right[key]),
    )
  );
}

function historyKind(): ConfigurationKind {
  return activeSection.value === "profiles" ? "export_profile" : "venue";
}

async function openHistory() {
  createMode.value = null;
  pendingDeletion.value = null;
  errorMessage.value = null;
  statusMessage.value = null;
  historyMode.value = true;
  historyItems.value = [];
  historyTotal.value = 0;
  historyError.value = null;
  await loadMoreHistory();
}

function closeHistory() {
  historyGeneration += 1;
  historyMode.value = false;
  isLoadingHistory.value = false;
  historyError.value = null;
}

async function loadMoreHistory() {
  if (isLoadingHistory.value) return;
  const kind = historyKind();
  const generation = ++historyGeneration;
  isLoadingHistory.value = true;
  historyError.value = null;
  try {
    const page = await getConfigurationHistory(kind, {
      limit: 50,
      offset: historyItems.value.length,
    });
    if (
      generation !== historyGeneration ||
      !historyMode.value ||
      kind !== historyKind()
    ) {
      return;
    }
    historyItems.value.push(...page.items);
    historyTotal.value = page.total;
  } catch (error) {
    if (generation !== historyGeneration || !historyMode.value) return;
    historyError.value = errorText(
      error,
      "Could not load configuration history.",
    );
  } finally {
    if (generation === historyGeneration) isLoadingHistory.value = false;
  }
}

function historyActionLabel(action: ConfigurationHistoryAction) {
  const labels: Record<ConfigurationHistoryAction, string> = {
    change: "Changed",
    create: "Created",
    override: "Overrode default",
    update: "Updated",
    restore_default: "Restored default",
    delete: "Deleted",
  };
  return labels[action];
}

function hasExactHistoryDiff(event: ConfigurationHistoryEvent) {
  if (event.action === "create") {
    return event.before_data === null && event.after_data !== null;
  }
  if (event.action === "delete") {
    return event.before_data !== null && event.after_data === null;
  }
  return event.before_data !== null && event.after_data !== null;
}

function beforeHistoryRevisionLabel(event: ConfigurationHistoryEvent) {
  if (event.action === "create") return "Empty";
  if (event.action === "override") return "Built-in default";
  return event.revision > 1
    ? `Revision ${event.revision - 1}`
    : "Previous state";
}

function afterHistoryRevisionLabel(event: ConfigurationHistoryEvent) {
  if (event.action === "delete") return "Deleted";
  if (event.action === "restore_default") return "Built-in default";
  return `Revision ${event.revision}`;
}

function formatHistoryTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function onDialogKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeSettings();
    return;
  }
  if (event.key !== "Tab" || !dialog.value) return;
  const focusable = Array.from(
    dialog.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.getClientRects().length > 0);
  const first = focusable[0];
  const last = focusable.at(-1);
  if (!first || !last) return;
  if (
    event.shiftKey &&
    (document.activeElement === first || document.activeElement === dialog.value)
  ) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneData<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim()
    ? error.message
    : fallback;
}

defineExpose({ openSettings });
</script>

<template>
  <div class="settings-panel">
    <button
      ref="trigger"
      type="button"
      class="settings-trigger"
      aria-haspopup="dialog"
      :aria-expanded="isOpen"
      aria-label="Application settings"
      @click="openSettings"
    >
      <AppIcon name="gear" />
    </button>

    <Teleport v-if="isOpen" to="body">
      <div class="settings-backdrop" @click.self="closeSettings">
        <section
          ref="dialog"
          class="settings-sheet"
          role="dialog"
          aria-modal="true"
          aria-labelledby="settings-heading"
          tabindex="-1"
          @keydown="onDialogKeydown"
        >
          <header class="settings-sheet__header">
            <div>
              <p class="settings-eyebrow">Shared configuration</p>
              <h2 id="settings-heading">Application settings</h2>
              <p>Changes apply to every user and are recorded with your account.</p>
            </div>
            <button
              type="button"
              class="registration-close"
              aria-label="Close settings"
              :disabled="isBusy"
              @click="closeSettings"
            >
              <AppIcon name="x-lg" />
            </button>
          </header>

          <div class="settings-tabs" role="tablist" aria-label="Setting categories">
            <button
              type="button"
              role="tab"
              :aria-selected="activeSection === 'profiles'"
              @click="selectSection('profiles')"
            >
              Export profiles
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="activeSection === 'venues'"
              @click="selectSection('venues')"
            >
              Venue mappings
            </button>
          </div>

          <div v-if="isLoading" class="settings-state" role="status">
            Loading settings…
          </div>
          <div v-else-if="!configuration" class="settings-state">
            <p>{{ errorMessage ?? "Settings are unavailable." }}</p>
            <button type="button" class="button-secondary" @click="loadConfiguration()">
              Retry
            </button>
          </div>

          <div v-else class="settings-workspace">
            <aside class="settings-list" aria-label="Available settings">
              <div class="settings-list__toolbar">
                <span>{{ activeSection === "profiles" ? "Profiles" : "Mappings" }}</span>
                <div class="settings-list__toolbar-actions">
                  <button
                    type="button"
                    :aria-label="
                      activeSection === 'profiles'
                        ? 'View export profile history'
                        : 'View venue mapping history'
                    "
                    :aria-pressed="historyMode"
                    :disabled="isBusy"
                    @click="openHistory"
                  >
                    <AppIcon name="clock-history" />
                  </button>
                  <button
                    type="button"
                    :aria-label="
                      activeSection === 'profiles'
                        ? 'Add export profile'
                        : 'Add venue mapping'
                    "
                    :disabled="isBusy"
                    @click="
                      activeSection === 'profiles'
                        ? startAddingProfile()
                        : startAddingVenue()
                    "
                  >
                    <AppIcon name="plus-lg" />
                  </button>
                </div>
              </div>
              <div class="settings-list__items">
                <template v-if="activeSection === 'profiles'">
                  <button
                    v-for="entry in configuration.export_profiles"
                    :key="entry.key"
                    type="button"
                    :class="{
                      selected:
                        !historyMode &&
                        createMode !== 'profile' &&
                        entry.key === selectedProfileId,
                    }"
                    @click="selectProfile(entry.key)"
                  >
                    <strong>{{ entry.data.display_name }}</strong>
                    <span>{{ entry.key }}</span>
                  </button>
                </template>
                <template v-else>
                  <button
                    v-for="entry in configuration.venues"
                    :key="entry.key"
                    type="button"
                    :class="{
                      selected:
                        !historyMode &&
                        createMode !== 'venue' &&
                        entry.key === selectedVenueId,
                    }"
                    @click="selectVenue(entry.key)"
                  >
                    <strong>{{ entry.data.short_name }}</strong>
                    <span>{{ entry.data.full_name }}</span>
                  </button>
                </template>
              </div>
            </aside>

            <section
              v-if="historyMode"
              class="settings-editor settings-history"
              aria-labelledby="settings-history-heading"
            >
              <div class="settings-editor__heading">
                <div>
                  <h3 id="settings-history-heading">
                    {{
                      activeSection === "profiles"
                        ? "Export profile history"
                        : "Venue mapping history"
                    }}
                  </h3>
                  <p>
                    Shared changes, including settings that were later deleted.
                  </p>
                </div>
                <button
                  type="button"
                  class="button-secondary"
                  @click="closeHistory"
                >
                  Done
                </button>
              </div>
              <p
                v-if="historyError"
                class="settings-history__message error"
                role="alert"
              >
                {{ historyError }}
              </p>
              <div
                v-if="isLoadingHistory && historyItems.length === 0"
                class="settings-history__empty"
                role="status"
              >
                Loading history…
              </div>
              <div
                v-else-if="historyItems.length === 0 && !historyError"
                class="settings-history__empty"
              >
                No changes have been recorded yet.
              </div>
              <ol v-else class="settings-history__list">
                <li v-for="event in historyItems" :key="event.id">
                  <details>
                    <summary>
                      <span
                        class="settings-history__action"
                        :data-action="event.action"
                      >
                        {{ historyActionLabel(event.action) }}
                      </span>
                      <span class="settings-history__identity">
                        <strong>{{ event.key }}</strong>
                        <small>Revision {{ event.revision }}</small>
                      </span>
                      <span class="settings-history__attribution">
                        {{ event.actor.email }}
                        <time :datetime="event.occurred_at">
                          {{ formatHistoryTime(event.occurred_at) }}
                        </time>
                      </span>
                    </summary>
                    <UnifiedDiff
                      v-if="hasExactHistoryDiff(event)"
                      class="settings-history__diff"
                      :before="event.before_data"
                      :after="event.after_data"
                      :before-label="beforeHistoryRevisionLabel(event)"
                      :after-label="afterHistoryRevisionLabel(event)"
                      :accessible-label="`${event.key} revision ${event.revision} changes`"
                      format="json"
                    />
                    <p
                      v-else
                      class="settings-history__unavailable"
                      role="note"
                    >
                      An exact diff is unavailable because this legacy event
                      does not contain a complete previous and next snapshot.
                    </p>
                  </details>
                </li>
              </ol>
              <button
                v-if="historyItems.length < historyTotal"
                type="button"
                class="button-secondary settings-history__more"
                :disabled="isLoadingHistory"
                @click="loadMoreHistory"
              >
                {{ isLoadingHistory ? "Loading…" : "Load older changes" }}
              </button>
            </section>

            <form
              v-else-if="
                activeSection === 'profiles' &&
                (createMode === 'profile' || selectedProfile)
              "
              class="settings-editor"
              @submit.prevent="saveProfile"
            >
              <div class="settings-editor__heading">
                <div>
                  <h3>
                    {{
                      createMode === "profile"
                        ? "New export profile"
                        : selectedProfile?.data.display_name
                    }}
                  </h3>
                  <p v-if="createMode === 'profile'">
                    Starts as a copy of the selected profile.
                  </p>
                  <p v-else-if="selectedProfile">
                    <template v-if="selectedProfile.built_in">
                      Built-in profile ·
                      {{
                        selectedProfile.revision > 0
                          ? `Shared override, revision ${selectedProfile.revision}`
                          : "Default"
                      }}
                    </template>
                    <template v-else>
                      Custom profile · Revision {{ selectedProfile.revision }}
                    </template>
                  </p>
                </div>
                <div class="settings-editor__actions">
                  <button
                    v-if="
                      createMode !== 'profile' &&
                      selectedProfile &&
                      selectedProfile.revision > 0
                    "
                    type="button"
                    :class="
                      selectedProfile.built_in
                        ? 'button-secondary'
                        : 'button-danger-quiet'
                    "
                    :disabled="isBusy"
                    @click="requestProfileDeletion"
                  >
                    {{
                      selectedProfile.built_in
                        ? "Restore Default…"
                        : "Delete…"
                    }}
                  </button>
                  <button
                    v-if="createMode === 'profile'"
                    type="button"
                    class="button-secondary"
                    :disabled="isBusy"
                    @click="cancelAddition"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    class="button-primary"
                    :disabled="isBusy || !canSaveProfile"
                  >
                    {{
                      isSaving
                        ? "Saving…"
                        : createMode === "profile"
                          ? "Add profile"
                          : "Save profile"
                    }}
                  </button>
                </div>
              </div>
              <div
                v-if="pendingDeletion?.section === 'profiles'"
                class="settings-confirm"
                role="alert"
              >
                <div>
                  <strong>
                    {{
                      pendingDeletion.builtIn
                        ? "Restore the built-in profile?"
                        : "Delete this profile?"
                    }}
                  </strong>
                  <p>
                    {{
                      pendingDeletion.builtIn
                        ? "The shared override will be removed. The profile will use the definition shipped with BibMgR."
                        : "It will disappear from every user's export choices. Stored references are unchanged."
                    }}
                  </p>
                </div>
                <div>
                  <button
                    type="button"
                    class="button-secondary"
                    :disabled="isDeleting"
                    @click="pendingDeletion = null"
                  >
                    Cancel
                  </button>
                  <button
                    ref="confirmationAction"
                    type="button"
                    :class="
                      pendingDeletion.builtIn
                        ? 'button-primary'
                        : 'button-danger'
                    "
                    :disabled="isDeleting"
                    @click="confirmDeletion"
                  >
                    {{
                      isDeleting
                        ? "Working…"
                        : pendingDeletion.builtIn
                          ? "Restore Default"
                          : "Delete"
                    }}
                  </button>
                </div>
              </div>
              <label
                v-if="createMode === 'profile'"
                class="settings-field settings-field--identifier"
              >
                <span>Profile ID <small>lowercase kebab-case</small></span>
                <input
                  v-model.trim="newConfigurationKey"
                  required
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                  placeholder="my-export-profile"
                  :disabled="isBusy"
                />
              </label>
              <ExportProfileEditor
                v-if="profileDraft"
                v-model="profileDraft"
                :profile-id="profileDraftId"
                :disabled="isBusy"
              />
            </form>

            <form
              v-else-if="
                activeSection === 'venues' &&
                (createMode === 'venue' || selectedVenue) &&
                venueDraft
              "
              class="settings-editor"
              @submit.prevent="saveVenue"
            >
              <div class="settings-editor__heading">
                <div>
                  <h3>
                    {{
                      createMode === "venue"
                        ? "New venue mapping"
                        : venueDraft.short_name
                    }}
                  </h3>
                  <p v-if="createMode === 'venue'">
                    Add a canonical name and the aliases found in BibTeX.
                  </p>
                  <p v-else-if="selectedVenue">
                    <template v-if="selectedVenue.built_in">
                      Built-in mapping ·
                      {{
                        selectedVenue.revision > 0
                          ? `Shared override, revision ${selectedVenue.revision}`
                          : "Default"
                      }}
                    </template>
                    <template v-else>
                      Custom mapping · Revision {{ selectedVenue.revision }}
                    </template>
                  </p>
                </div>
                <div class="settings-editor__actions">
                  <button
                    v-if="
                      createMode !== 'venue' &&
                      selectedVenue &&
                      selectedVenue.revision > 0
                    "
                    type="button"
                    :class="
                      selectedVenue.built_in
                        ? 'button-secondary'
                        : 'button-danger-quiet'
                    "
                    :disabled="isBusy"
                    @click="requestVenueDeletion"
                  >
                    {{
                      selectedVenue.built_in
                        ? "Restore Default…"
                        : "Delete…"
                    }}
                  </button>
                  <button
                    v-if="createMode === 'venue'"
                    type="button"
                    class="button-secondary"
                    :disabled="isBusy"
                    @click="cancelAddition"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    class="button-primary"
                    :disabled="isBusy || !canSaveVenue"
                  >
                    {{
                      isSaving
                        ? "Saving…"
                        : createMode === "venue"
                          ? "Add mapping"
                          : "Save mapping"
                    }}
                  </button>
                </div>
              </div>
              <div
                v-if="pendingDeletion?.section === 'venues'"
                class="settings-confirm"
                role="alert"
              >
                <div>
                  <strong>
                    {{
                      pendingDeletion.builtIn
                        ? "Restore the built-in mapping?"
                        : "Delete this mapping?"
                    }}
                  </strong>
                  <p>
                    {{
                      pendingDeletion.builtIn
                        ? "The shared override will be removed. The mapping will use the definition shipped with BibMgR."
                        : "Future exports will no longer resolve this venue through the deleted mapping."
                    }}
                  </p>
                </div>
                <div>
                  <button
                    type="button"
                    class="button-secondary"
                    :disabled="isDeleting"
                    @click="pendingDeletion = null"
                  >
                    Cancel
                  </button>
                  <button
                    ref="confirmationAction"
                    type="button"
                    :class="
                      pendingDeletion.builtIn
                        ? 'button-primary'
                        : 'button-danger'
                    "
                    :disabled="isDeleting"
                    @click="confirmDeletion"
                  >
                    {{
                      isDeleting
                        ? "Working…"
                        : pendingDeletion.builtIn
                          ? "Restore Default"
                          : "Delete"
                    }}
                  </button>
                </div>
              </div>
              <div class="settings-form-grid">
                <label
                  v-if="createMode === 'venue'"
                  class="settings-field settings-field--wide"
                >
                  <span>Mapping ID <small>lowercase kebab-case</small></span>
                  <input
                    v-model.trim="newConfigurationKey"
                    required
                    pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                    placeholder="my-conference"
                    :disabled="isBusy"
                  />
                </label>
                <label class="settings-field settings-field--wide">
                  <span>Full name</span>
                  <input
                    v-model.trim="venueDraft.full_name"
                    required
                    :disabled="isBusy"
                  />
                </label>
                <label class="settings-field">
                  <span>Abbreviation</span>
                  <input
                    v-model.trim="venueDraft.short_name"
                    required
                    :disabled="isBusy"
                  />
                </label>
                <label class="settings-field">
                  <span>Kind</span>
                  <select v-model="venueDraft.kind" :disabled="isBusy">
                    <option
                      v-for="kind in venueKinds"
                      :key="kind"
                      :value="kind"
                    >
                      {{ kind }}
                    </option>
                  </select>
                </label>
                <label class="settings-field settings-field--wide">
                  <span>Aliases <small>One per line</small></span>
                  <textarea
                    :value="aliasesText(venueDraft)"
                    rows="7"
                    :disabled="isBusy"
                    @input="updateAliases"
                  ></textarea>
                </label>
              </div>
            </form>
          </div>

          <p v-if="errorMessage && configuration" class="settings-message error" role="alert">
            {{ errorMessage }}
          </p>
          <p v-if="statusMessage" class="settings-message success" role="status">
            {{ statusMessage }}
          </p>
        </section>
      </div>
    </Teleport>
  </div>
</template>
