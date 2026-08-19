<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
} from "vue";
import { previewExportProfile } from "../api/configuration";
import type {
  ExportFieldCase,
  ExportLineEnding,
  ExportMonthFormat,
  ExportProfileData,
  ExportValueDelimiter,
  PreprintRepresentation,
} from "../types/configuration";
import type { BibtexExportResult } from "../types/bibtex";
import {
  exportProfileErrors,
  hasField,
  profileFieldNames,
  uniqueFields,
  validFieldName,
  withoutField,
} from "../utils/exportProfile";
import AppIcon from "./AppIcon.vue";
import BibtexCodeBlock from "./BibtexCodeBlock.vue";

const props = defineProps<{
  profileId: string;
  disabled?: boolean;
}>();
const model = defineModel<ExportProfileData>({ required: true });

const DEFAULT_PREVIEW_SOURCE = `@inproceedings{smith-2026-example,
  title = {A Practical Study of Language Models},
  author = {Smith, Alex and Tanaka, Mei},
  booktitle = {Annual Meeting of the Association for Computational Linguistics},
  month = {7},
  year = {2026},
  pages = {101--112},
  doi = {10.0000/example},
  url = {https://example.org/paper}
}`;

const validationPolicies = [
  { value: "modern", label: "Modern" },
  { value: "classical-bst", label: "Classical BST" },
  { value: "acl", label: "ACL" },
];
const newField = ref("");
const newEntryType = ref("");
const fieldInput = ref<HTMLInputElement | null>(null);
const localMessage = ref<string | null>(null);
const previewSource = ref(DEFAULT_PREVIEW_SOURCE);
const previewResult = ref<BibtexExportResult | null>(null);
const previewError = ref<string | null>(null);
const previewLoading = ref(false);
const jsonCopied = ref(false);
let previewTimer: ReturnType<typeof setTimeout> | undefined;
let previewController: AbortController | undefined;
let previewGeneration = 0;
let copiedTimer: ReturnType<typeof setTimeout> | undefined;

const draft = computed(() => ({
  ...model.value,
  profile: props.profileId || model.value.profile,
}));
const errors = computed(() => exportProfileErrors(draft.value));
const configuredFields = computed(() => profileFieldNames(model.value));
const fieldRows = computed(() => {
  const renames = Object.entries(model.value.field_renames);
  const sources = renames.map(([source]) => source);
  return configuredFields.value
    .filter((field) => !hasField(sources, field))
    .map((field) => {
      const rename = renames.find(([, target]) =>
        target.toLowerCase() === field.toLowerCase(),
      );
      return rename
        ? { source: rename[0], output: field }
        : { source: field, output: field };
    });
});
const includesUnlistedFields = computed(
  () => model.value.field_selection.allowed_fields === null,
);
const canonicalJson = computed(() =>
  JSON.stringify(draft.value, null, 2),
);
const indentOptions = computed(() => {
  const options = [
    { value: "  ", label: "2 spaces" },
    { value: "    ", label: "4 spaces" },
    { value: "\t", label: "Tab" },
    { value: "", label: "No indentation" },
  ];
  if (!options.some((option) => option.value === model.value.indent)) {
    options.push({
      value: model.value.indent,
      label: "Current custom whitespace",
    });
  }
  return options;
});

watch(
  [draft, previewSource],
  () => schedulePreview(),
  { deep: true, immediate: true },
);

onBeforeUnmount(() => {
  if (previewTimer) clearTimeout(previewTimer);
  if (copiedTimer) clearTimeout(copiedTimer);
  previewController?.abort();
});

function patch(changes: Partial<ExportProfileData>) {
  model.value = {
    ...model.value,
    ...changes,
  };
}

function patchSelection(
  changes: Partial<ExportProfileData["field_selection"]>,
) {
  patch({
    field_selection: {
      ...model.value.field_selection,
      ...changes,
    },
  });
}

function eventValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLSelectElement).value;
}

function eventChecked(event: Event) {
  return (event.target as HTMLInputElement).checked;
}

function fieldIncluded(field: string) {
  if (
    hasField(model.value.excluded_fields, field) ||
    hasField(model.value.field_selection.excluded_fields, field)
  ) {
    return false;
  }
  const allowed = model.value.field_selection.allowed_fields;
  return allowed === null || hasField(allowed, field);
}

function setFieldIncluded(field: string, included: boolean) {
  const allowed = model.value.field_selection.allowed_fields;
  const legacyExcluded = withoutField(model.value.excluded_fields, field);
  let selectedExcluded = withoutField(
    model.value.field_selection.excluded_fields,
    field,
  );
  if (allowed === null) {
    if (!included) selectedExcluded.push(field);
    patch({
      excluded_fields: legacyExcluded,
      field_selection: {
        allowed_fields: null,
        excluded_fields: uniqueFields(selectedExcluded),
      },
    });
    return;
  }
  patch({
    excluded_fields: legacyExcluded,
    field_selection: {
      allowed_fields: included
        ? uniqueFields([...allowed, field])
        : withoutField(allowed, field),
      excluded_fields: selectedExcluded,
    },
  });
}

function setIncludesUnlistedFields(included: boolean) {
  if (included) {
    patchSelection({ allowed_fields: null });
    return;
  }
  patchSelection({
    allowed_fields: uniqueFields(
      fieldRows.value
        .map((row) => row.output)
        .filter((field) => fieldIncluded(field)),
    ),
  });
}

function fieldProtected(field: string) {
  return hasField(model.value.case_protected_fields, field);
}

function setFieldProtected(field: string, protectedValue: boolean) {
  patch({
    case_protected_fields: protectedValue
      ? uniqueFields([...model.value.case_protected_fields, field])
      : withoutField(model.value.case_protected_fields, field),
  });
}

function fieldRename(source: string) {
  const canonicalSource = Object.keys(model.value.field_renames).find(
    (candidate) => candidate.toLowerCase() === source.toLowerCase(),
  );
  return canonicalSource ? model.value.field_renames[canonicalSource] : "";
}

function setFieldRename(
  source: string,
  currentOutput: string,
  targetValue: string,
) {
  const target = targetValue.trim();
  if (target && !validFieldName(target)) {
    localMessage.value =
      "Export names may contain letters, numbers, underscores, and hyphens.";
    return;
  }
  if (target && source.toLowerCase() === target.toLowerCase()) {
    localMessage.value =
      "Leave the export name empty when the field name is unchanged.";
    return;
  }
  const nextOutput = target || source;
  const fieldRenames = { ...model.value.field_renames };
  for (const candidate of Object.keys(fieldRenames)) {
    if (candidate.toLowerCase() === source.toLowerCase()) {
      delete fieldRenames[candidate];
    }
  }
  if (target) fieldRenames[source] = target;

  const replaceOutput = (fields: string[]) =>
    uniqueFields(
      fields.map((field) =>
        field.toLowerCase() === currentOutput.toLowerCase()
          ? nextOutput
          : field,
      ),
    );
  const allowed = model.value.field_selection.allowed_fields;
  patch({
    field_renames: fieldRenames,
    field_order: replaceOutput(model.value.field_order),
    case_protected_fields: replaceOutput(
      model.value.case_protected_fields,
    ),
    excluded_fields: replaceOutput(model.value.excluded_fields),
    field_selection: {
      allowed_fields: allowed ? replaceOutput(allowed) : null,
      excluded_fields: replaceOutput(
        model.value.field_selection.excluded_fields,
      ),
    },
  });
  localMessage.value = null;
}

function moveField(field: string, offset: -1 | 1) {
  const order = [...model.value.field_order];
  const index = order.findIndex(
    (candidate) => candidate.toLowerCase() === field.toLowerCase(),
  );
  const target = index + offset;
  if (index < 0 || target < 0 || target >= order.length) return;
  [order[index], order[target]] = [order[target], order[index]];
  patch({ field_order: order });
}

function fieldOrderIndex(field: string) {
  return model.value.field_order.findIndex(
    (candidate) => candidate.toLowerCase() === field.toLowerCase(),
  );
}

async function addField() {
  const field = newField.value.trim();
  if (!validFieldName(field)) {
    localMessage.value =
      "Field names may contain letters, numbers, underscores, and hyphens.";
    await nextTick();
    fieldInput.value?.focus();
    return;
  }
  if (hasField(configuredFields.value, field)) {
    localMessage.value = `Field “${field}” is already configured.`;
    await nextTick();
    fieldInput.value?.focus();
    return;
  }
  const allowed = model.value.field_selection.allowed_fields;
  patch({
    field_order: [...model.value.field_order, field],
    field_selection: {
      ...model.value.field_selection,
      allowed_fields: allowed ? [...allowed, field] : null,
    },
  });
  newField.value = "";
  localMessage.value = null;
  await nextTick();
  fieldInput.value?.focus();
}

async function addEntryType() {
  const entryType = newEntryType.value.trim();
  if (!validFieldName(entryType)) {
    localMessage.value =
      "Entry types may contain letters, numbers, underscores, and hyphens.";
    return;
  }
  if (hasField(model.value.supported_entry_types, entryType)) {
    localMessage.value = `Entry type “${entryType}” is already listed.`;
    return;
  }
  patch({
    supported_entry_types: [
      ...model.value.supported_entry_types,
      entryType,
    ],
  });
  newEntryType.value = "";
  localMessage.value = null;
}

function removeEntryType(entryType: string) {
  patch({
    supported_entry_types: withoutField(
      model.value.supported_entry_types,
      entryType,
    ),
  });
}

function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer);
  previewController?.abort();
  previewLoading.value = false;
  if (
    !props.profileId ||
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(props.profileId) ||
    errors.value.length > 0
  ) {
    previewResult.value = null;
    previewError.value = props.profileId
      ? "Resolve the highlighted settings to preview this profile."
      : "Enter a valid profile ID to generate a preview.";
    return;
  }
  previewError.value = null;
  previewTimer = setTimeout(() => void loadPreview(), 300);
}

async function loadPreview() {
  const generation = ++previewGeneration;
  previewController?.abort();
  previewController = new AbortController();
  previewLoading.value = true;
  previewError.value = null;
  try {
    const result = await previewExportProfile(
      {
        source: previewSource.value,
        data: draft.value,
        venue_name_style: "full",
      },
      previewController.signal,
    );
    if (generation !== previewGeneration) return;
    previewResult.value = result;
  } catch (error) {
    if (generation !== previewGeneration || isAbortError(error)) return;
    previewResult.value = null;
    previewError.value =
      error instanceof Error && error.message
        ? error.message
        : "Could not generate the preview.";
  } finally {
    if (generation === previewGeneration) previewLoading.value = false;
  }
}

async function copyCanonicalJson() {
  if (!navigator.clipboard) return;
  await navigator.clipboard.writeText(canonicalJson.value);
  jsonCopied.value = true;
  if (copiedTimer) clearTimeout(copiedTimer);
  copiedTimer = setTimeout(() => {
    jsonCopied.value = false;
  }, 1800);
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
</script>

<template>
  <div class="profile-editor">
    <section class="profile-group" aria-labelledby="profile-details-heading">
      <div class="profile-group__heading">
        <div>
          <h4 id="profile-details-heading">Profile details</h4>
          <p>Name the profile and choose how generated BibTeX is validated.</p>
        </div>
      </div>
      <div class="profile-grid">
        <label class="settings-field">
          <span>Display name</span>
          <input
            :value="model.display_name"
            required
            :disabled="disabled"
            autocomplete="off"
            @input="patch({ display_name: eventValue($event) })"
          />
        </label>
        <label class="settings-field">
          <span>Validation baseline</span>
          <select
            :value="model.validation_profile"
            :disabled="disabled"
            @change="patch({ validation_profile: eventValue($event) })"
          >
            <option
              v-for="policy in validationPolicies"
              :key="policy.value"
              :value="policy.value"
            >
              {{ policy.label }}
            </option>
          </select>
        </label>
        <label class="settings-field profile-grid__wide">
          <span>Description</span>
          <textarea
            :value="model.description"
            required
            rows="2"
            :disabled="disabled"
            @input="patch({ description: eventValue($event) })"
          ></textarea>
        </label>
        <label class="settings-field">
          <span>Preprint representation</span>
          <select
            :value="model.preprint_representation"
            :disabled="disabled"
            @change="
              patch({
                preprint_representation: eventValue(
                  $event,
                ) as PreprintRepresentation,
              })
            "
          >
            <option value="misc-eprint">Misc with eprint fields</option>
            <option value="misc-howpublished">Misc with howpublished</option>
            <option value="article-journal">Article with journal</option>
          </select>
        </label>
        <label class="settings-field">
          <span>Unknown work types</span>
          <select
            :value="model.allow_unknown_work_type ? 'allow' : 'reject'"
            :disabled="disabled"
            @change="
              patch({
                allow_unknown_work_type: eventValue($event) === 'allow',
              })
            "
          >
            <option value="allow">Export with a general mapping</option>
            <option value="reject">Require a known mapping</option>
          </select>
        </label>
      </div>
    </section>

    <section class="profile-group" aria-labelledby="profile-fields-heading">
      <div class="profile-group__heading">
        <div>
          <h4 id="profile-fields-heading">Output fields</h4>
          <p>
            Choose exported fields, their order, case protection, and output
            names.
          </p>
        </div>
        <label class="profile-switch">
          <input
            type="checkbox"
            :checked="includesUnlistedFields"
            :disabled="disabled"
            @change="setIncludesUnlistedFields(eventChecked($event))"
          />
          <span>Include unlisted fields</span>
        </label>
      </div>

      <div class="profile-field-table">
        <div class="profile-field-table__header" aria-hidden="true">
          <span>Order</span>
          <span>Field</span>
          <span>Include</span>
          <span>Protect case</span>
          <span>Export name</span>
        </div>
        <div
          v-for="row in fieldRows"
          :key="row.source.toLowerCase()"
          class="profile-field-row"
        >
          <span class="profile-field-order">
            <button
              type="button"
              class="profile-icon-button"
              :aria-label="`Move ${row.output} earlier`"
              :disabled="
                disabled ||
                fieldOrderIndex(row.output) <= 0
              "
              @click="moveField(row.output, -1)"
            >
              <AppIcon name="chevron-up" />
            </button>
            <button
              type="button"
              class="profile-icon-button"
              :aria-label="`Move ${row.output} later`"
              :disabled="
                disabled ||
                fieldOrderIndex(row.output) < 0 ||
                fieldOrderIndex(row.output) === model.field_order.length - 1
              "
              @click="moveField(row.output, 1)"
            >
              <AppIcon name="chevron-down" />
            </button>
          </span>
          <span class="profile-field-name">
            <code>{{ row.source }}</code>
            <small v-if="row.source !== row.output">
              <AppIcon name="arrow-right" />
              {{ row.output }}
            </small>
          </span>
          <label class="profile-checkbox">
            <input
              type="checkbox"
              :checked="fieldIncluded(row.output)"
              :disabled="disabled"
              :aria-label="`Include ${row.output}`"
              @change="setFieldIncluded(row.output, eventChecked($event))"
            />
          </label>
          <label class="profile-checkbox">
            <input
              type="checkbox"
              :checked="fieldProtected(row.output)"
              :disabled="disabled"
              :aria-label="`Protect ${row.output} from case changes`"
              @change="
                setFieldProtected(row.output, eventChecked($event))
              "
            />
          </label>
          <input
            class="profile-rename"
            :value="fieldRename(row.source)"
            :disabled="disabled"
            :aria-label="`Export name for ${row.source}`"
            placeholder="Unchanged"
            @change="
              setFieldRename(
                row.source,
                row.output,
                eventValue($event),
              )
            "
          />
        </div>
      </div>

      <div class="profile-add-row">
        <label class="settings-field">
          <span>Add a field</span>
          <input
            ref="fieldInput"
            v-model.trim="newField"
            :disabled="disabled"
            placeholder="abstract"
            pattern="[A-Za-z0-9_-]+"
            @keydown.enter.prevent="addField"
          />
        </label>
        <button
          type="button"
          class="button-secondary"
          :disabled="disabled || !newField"
          @click="addField"
        >
          <AppIcon name="plus-lg" />
          Add field
        </button>
      </div>
    </section>

    <section class="profile-group" aria-labelledby="profile-format-heading">
      <div class="profile-group__heading">
        <div>
          <h4 id="profile-format-heading">BibTeX formatting</h4>
          <p>Control value syntax and file-level formatting.</p>
        </div>
      </div>
      <div class="profile-grid profile-grid--compact">
        <label class="settings-field">
          <span>Field names</span>
          <select
            :value="model.field_case"
            :disabled="disabled"
            @change="
              patch({
                field_case: eventValue($event) as ExportFieldCase,
              })
            "
          >
            <option value="canonical">Canonical spelling</option>
            <option value="lowercase">Lowercase</option>
          </select>
        </label>
        <label class="settings-field">
          <span>Value delimiters</span>
          <select
            :value="model.value_delimiter"
            :disabled="disabled"
            @change="
              patch({
                value_delimiter: eventValue(
                  $event,
                ) as ExportValueDelimiter,
              })
            "
          >
            <option value="braces">Braces {…}</option>
            <option value="quotes">Quotation marks "…"</option>
          </select>
        </label>
        <label class="settings-field">
          <span>Month values</span>
          <select
            :value="model.month_format"
            :disabled="disabled"
            @change="
              patch({
                month_format: eventValue($event) as ExportMonthFormat,
              })
            "
          >
            <option value="numeric">Numeric</option>
            <option value="bibtex-macro">BibTeX macros</option>
          </select>
        </label>
        <label class="settings-field">
          <span>Indentation</span>
          <select
            :value="model.indent"
            :disabled="disabled"
            @change="patch({ indent: eventValue($event) })"
          >
            <option
              v-for="option in indentOptions"
              :key="`${option.label}-${option.value}`"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="settings-field">
          <span>Line endings</span>
          <select
            :value="model.line_ending"
            :disabled="disabled"
            @change="
              patch({
                line_ending: eventValue($event) as ExportLineEnding,
              })
            "
          >
            <option value="lf">LF (Unix/macOS)</option>
            <option value="cr-lf">CRLF (Windows)</option>
          </select>
        </label>
        <label class="profile-switch profile-switch--row">
          <input
            type="checkbox"
            :checked="model.trailing_comma"
            :disabled="disabled"
            @change="patch({ trailing_comma: eventChecked($event) })"
          />
          <span>Trailing comma on the last field</span>
        </label>
      </div>
    </section>

    <section class="profile-group" aria-labelledby="profile-entry-types-heading">
      <div class="profile-group__heading">
        <div>
          <h4 id="profile-entry-types-heading">Supported entry types</h4>
          <p>
            Leave empty to use general mappings, or list target-specific entry
            types that may be preserved.
          </p>
        </div>
      </div>
      <div
        v-if="model.supported_entry_types.length"
        class="profile-tokens"
        aria-label="Supported entry types"
      >
        <span
          v-for="entryType in model.supported_entry_types"
          :key="entryType.toLowerCase()"
        >
          <code>{{ entryType }}</code>
          <button
            type="button"
            :aria-label="`Remove ${entryType}`"
            :disabled="disabled"
            @click="removeEntryType(entryType)"
          >
            <AppIcon name="x-lg" />
          </button>
        </span>
      </div>
      <p v-else class="profile-empty-note">General mappings are enabled.</p>
      <div class="profile-add-row">
        <label class="settings-field">
          <span>Add an entry type</span>
          <input
            v-model.trim="newEntryType"
            :disabled="disabled"
            placeholder="inproceedings"
            pattern="[A-Za-z0-9_-]+"
            @keydown.enter.prevent="addEntryType"
          />
        </label>
        <button
          type="button"
          class="button-secondary"
          :disabled="disabled || !newEntryType"
          @click="addEntryType"
        >
          <AppIcon name="plus-lg" />
          Add type
        </button>
      </div>
    </section>

    <details class="profile-advanced">
      <summary>
        <span>
          <strong>Advanced</strong>
          <small>Candidate generation and canonical data</small>
        </span>
      </summary>
      <div class="profile-advanced__content">
        <fieldset>
          <legend>Generate candidate fields</legend>
          <label class="profile-switch profile-switch--row">
            <input
              type="checkbox"
              :checked="model.include_doi"
              :disabled="disabled"
              @change="patch({ include_doi: eventChecked($event) })"
            />
            <span>DOI</span>
          </label>
          <label class="profile-switch profile-switch--row">
            <input
              type="checkbox"
              :checked="model.include_url"
              :disabled="disabled"
              @change="patch({ include_url: eventChecked($event) })"
            />
            <span>URL</span>
          </label>
          <label class="profile-switch profile-switch--row">
            <input
              type="checkbox"
              :checked="model.include_extra_fields"
              :disabled="disabled"
              @change="
                patch({ include_extra_fields: eventChecked($event) })
              "
            />
            <span>Additional source fields</span>
          </label>
        </fieldset>
        <div class="profile-json">
          <div>
            <span>Canonical profile data</span>
            <button
              type="button"
              class="button-secondary"
              :disabled="disabled"
              @click="copyCanonicalJson"
            >
              <AppIcon :name="jsonCopied ? 'check2' : 'copy'" />
              {{ jsonCopied ? "Copied" : "Copy JSON" }}
            </button>
          </div>
          <pre
            data-testid="export-profile-json"
            tabindex="0"
          ><code>{{ canonicalJson }}</code></pre>
        </div>
      </div>
    </details>

    <div
      v-if="localMessage || errors.length"
      class="profile-validation"
      role="alert"
    >
      <AppIcon name="exclamation-circle" />
      <div>
        <p v-if="localMessage">{{ localMessage }}</p>
        <ul v-if="errors.length">
          <li v-for="error in errors" :key="error">{{ error }}</li>
        </ul>
      </div>
    </div>

    <section class="profile-preview" aria-labelledby="profile-preview-heading">
      <div class="profile-group__heading">
        <div>
          <h4 id="profile-preview-heading">Live preview</h4>
          <p>Rendered with this unsaved profile and the current venue mappings.</p>
        </div>
        <span v-if="previewLoading" role="status">Updating…</span>
      </div>
      <BibtexCodeBlock
        v-if="previewResult"
        :source="previewResult.source"
        accessible-label="Export profile preview"
        test-id="export-profile-preview"
      />
      <p v-else class="profile-preview__message" :class="{ error: previewError }">
        {{ previewError ?? "Preparing preview…" }}
      </p>
      <details class="profile-preview__source">
        <summary>Preview input</summary>
        <label class="settings-field">
          <span>Sample BibTeX</span>
          <textarea
            v-model="previewSource"
            rows="9"
            spellcheck="false"
            :disabled="disabled"
          ></textarea>
        </label>
      </details>
    </section>
  </div>
</template>

<style scoped>
.profile-editor {
  display: grid;
  gap: 16px;
}

.profile-group,
.profile-preview,
.profile-advanced {
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-group);
  background: var(--color-surface);
}

.profile-group__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.profile-group__heading h4,
.profile-advanced strong {
  margin: 0;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.profile-group__heading p,
.profile-advanced small {
  display: block;
  margin: 3px 0 0;
  color: var(--color-text-muted);
  font-size: 10.5px;
  line-height: 1.45;
}

.profile-group__heading > span {
  color: var(--color-text-muted);
  font-size: 10.5px;
}

.profile-grid {
  display: grid;
  gap: 13px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.profile-grid--compact {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.profile-grid__wide {
  grid-column: 1 / -1;
}

.profile-switch {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 550;
}

.profile-switch--row {
  align-self: end;
  min-height: 38px;
}

.profile-switch input,
.profile-checkbox input {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
}

.profile-field-table {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 12px;
}

.profile-field-table__header,
.profile-field-row {
  display: grid;
  min-width: 620px;
  align-items: center;
  grid-template-columns: 58px minmax(100px, 0.8fr) 62px 78px minmax(130px, 1fr);
}

.profile-field-table__header {
  min-height: 30px;
  background: var(--color-fill);
  color: var(--color-text-muted);
  font-size: 9.5px;
  font-weight: 650;
}

.profile-field-table__header > span,
.profile-field-row > * {
  min-width: 0;
  padding-inline: 8px;
}

.profile-field-row {
  min-height: 42px;
  border-top: 1px solid var(--color-border);
}

.profile-field-row code,
.profile-tokens code {
  overflow: hidden;
  color: var(--color-text);
  font-family: "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
  font-size: 10.5px;
  text-overflow: ellipsis;
}

.profile-field-name {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.profile-field-name small {
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-field-name small .app-icon {
  margin-right: 3px;
  font-size: 8px;
}

.profile-field-order {
  display: flex;
  padding-inline: 4px;
}

.profile-icon-button {
  display: grid;
  width: 24px;
  height: 28px;
  place-items: center;
  border-radius: 7px;
  background: transparent;
  color: var(--color-text-secondary);
}

.profile-icon-button:hover:not(:disabled) {
  background: var(--color-fill-hover);
  color: var(--color-text);
}

.profile-icon-button:disabled {
  opacity: 0.28;
}

.profile-checkbox {
  display: grid;
  place-items: center;
}

.profile-rename {
  width: calc(100% - 14px);
  min-height: 30px;
  padding: 5px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  outline: 0;
  background: var(--color-fill);
  color: var(--color-text);
  font: 10.5px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
}

.profile-rename:focus {
  border-color: rgb(0 122 255 / 48%);
  background: var(--color-surface);
  box-shadow: var(--shadow-focus);
}

.profile-add-row {
  display: grid;
  align-items: end;
  gap: 8px;
  max-width: 360px;
  margin-top: 12px;
  grid-template-columns: minmax(0, 1fr) auto;
}

.profile-add-row button {
  min-height: 38px;
  gap: 6px;
}

.profile-tokens {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.profile-tokens > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 6px 5px 9px;
  border-radius: 999px;
  background: var(--color-fill);
}

.profile-tokens button {
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-muted);
}

.profile-tokens button:hover:not(:disabled) {
  background: var(--color-fill-hover);
  color: var(--color-text);
}

.profile-empty-note {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 11px;
}

.profile-advanced {
  padding: 0;
}

.profile-advanced > summary,
.profile-preview__source > summary {
  display: flex;
  min-height: 52px;
  align-items: center;
  padding: 10px 16px;
  cursor: pointer;
  list-style: none;
}

.profile-advanced > summary::-webkit-details-marker,
.profile-preview__source > summary::-webkit-details-marker {
  display: none;
}

.profile-advanced > summary::after,
.profile-preview__source > summary::after {
  margin-left: auto;
  color: var(--color-text-muted);
  content: "\F282";
  font-family: bootstrap-icons;
  font-size: 11px;
  transition: transform 140ms var(--ease-out);
}

.profile-advanced[open] > summary::after,
.profile-preview__source[open] > summary::after {
  transform: rotate(90deg);
}

.profile-advanced__content {
  display: grid;
  gap: 16px;
  padding: 0 16px 16px;
}

.profile-advanced fieldset {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin: 0;
  padding: 0;
  border: 0;
}

.profile-advanced legend,
.profile-json > div > span {
  width: 100%;
  margin-bottom: 5px;
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.profile-json > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 7px;
}

.profile-json button {
  min-height: 30px;
  gap: 6px;
  padding-inline: 9px;
  font-size: 10.5px;
}

.profile-json pre {
  max-height: 320px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-radius: 11px;
  background: var(--color-code);
  color: var(--color-text-secondary);
  font: 10px/1.5 "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
  tab-size: 2;
}

.profile-validation {
  display: flex;
  gap: 9px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--color-danger-soft);
  color: var(--color-danger);
  font-size: 11px;
  line-height: 1.45;
}

.profile-validation p,
.profile-validation ul {
  margin: 0;
}

.profile-validation ul {
  padding-left: 17px;
}

.profile-preview {
  min-width: 0;
}

.profile-preview :deep(.bibtex-code-block) {
  max-height: 340px;
  margin: 0;
}

.profile-preview__message {
  margin: 0;
  padding: 14px;
  border-radius: 11px;
  background: var(--color-fill);
  color: var(--color-text-muted);
  font-size: 11px;
}

.profile-preview__message.error {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.profile-preview__source {
  margin-top: 10px;
  border-top: 1px solid var(--color-border);
}

.profile-preview__source > summary {
  min-height: 40px;
  padding-inline: 2px;
  color: var(--color-text-secondary);
  font-size: 10.5px;
  font-weight: 600;
}

@media (max-width: 920px) {
  .profile-grid--compact {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .profile-field-table {
    overflow-x: auto;
  }
}

@media (max-width: 540px) {
  .profile-group,
  .profile-preview {
    padding: 14px;
  }

  .profile-group__heading {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
  }

  .profile-grid,
  .profile-grid--compact {
    grid-template-columns: minmax(0, 1fr);
  }

  .profile-grid__wide {
    grid-column: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .profile-advanced > summary::after,
  .profile-preview__source > summary::after {
    transition: none;
  }
}
</style>
