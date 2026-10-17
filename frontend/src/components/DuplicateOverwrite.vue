<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { getReference, updateReference } from "../api/references";
import { DuplicateReviewError, type DuplicateFinding } from "../api/duplicates";
import type { Reference } from "../types/reference";
import DuplicateReview from "./DuplicateReview.vue";
import UnifiedDiff from "./UnifiedDiff.vue";

const props = defineProps<{ referenceId: string; source: string }>();
const emit = defineEmits<{ saved: [reference: Reference]; cancel: []; busy: [value: boolean] }>();
const panel = ref<HTMLElement | null>(null);
const duplicateReview = ref<InstanceType<typeof DuplicateReview> | null>(null);
const stored = ref<Reference>();
const loading = ref(false);
const saving = ref(false);
const error = ref<string>();
const findings = ref<DuplicateFinding[]>([]);
const confirmation = ref<string>();
let generation = 0;

async function load() {
  const current = ++generation;
  stored.value = undefined;
  error.value = undefined;
  findings.value = [];
  confirmation.value = undefined;
  loading.value = true;
  try {
    const reference = await getReference(props.referenceId);
    if (current !== generation) return;
    if (!reference.sourceRevision) throw new Error("The stored reference has no revision. Reload it before overwriting.");
    stored.value = reference;
  } catch (failure) {
    if (current === generation) error.value = failure instanceof Error ? failure.message : "Could not load reference.";
  } finally {
    if (current === generation) loading.value = false;
  }
}

async function save(confirmed = false) {
  if (!stored.value?.sourceRevision || saving.value || loading.value) return;
  const current = generation;
  saving.value = true;
  emit("busy", true);
  error.value = undefined;
  try {
    const reference = await updateReference(props.referenceId, {
      bibtex: props.source,
      source_revision: stored.value.sourceRevision,
      ...(confirmed && confirmation.value ? { duplicate_confirmation: confirmation.value } : {}),
    });
    if (current === generation) {
      emit("busy", false);
      emit("saved", reference);
    }
  } catch (failure) {
    if (current !== generation) return;
    findings.value = failure instanceof DuplicateReviewError ? failure.findings : [];
    confirmation.value = failure instanceof DuplicateReviewError ? failure.confirmationToken : undefined;
    error.value = failure instanceof Error ? failure.message : "Could not overwrite reference.";
    if (failure instanceof DuplicateReviewError) void duplicateReview.value?.reveal();
  } finally {
    saving.value = false;
    emit("busy", false);
  }
}

watch(() => [props.referenceId, props.source], load, { immediate: true });
onMounted(() => panel.value?.focus());
onBeforeUnmount(() => { generation += 1; });
</script>

<template>
  <section ref="panel" class="duplicate-overwrite" aria-label="Overwrite stored reference" tabindex="-1">
    <h3>Overwrite stored reference</h3>
    <p>Review the BibTeX changes before overwriting. Citation contexts and change history are kept.</p>
    <p v-if="loading" role="status">Loading stored reference…</p>
    <template v-if="stored">
      <h4>{{ stored.title }}</h4>
      <UnifiedDiff
        :before="stored.bibtex ?? ''"
        :after="source"
        before-label="Current BibTeX"
        after-label="Replacement BibTeX"
        accessible-label="BibTeX overwrite changes"
      />
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
    <DuplicateReview ref="duplicateReview" :findings="findings" :confirmation-token="confirmation" confirm-label="Confirm overwrite despite possible matches" :busy="saving" @confirm="save(true)" />
    <div class="duplicate-overwrite__actions">
      <button type="button" class="button-primary" :disabled="!stored || loading || saving || findings.length > 0" @click="save()">{{ saving ? 'Overwriting…' : 'Confirm overwrite' }}</button>
      <button v-if="error" type="button" class="button-secondary" :disabled="loading || saving" @click="load">Reload stored reference</button>
      <button type="button" class="button-secondary" :disabled="saving" @click="$emit('cancel')">Cancel overwrite</button>
    </div>
  </section>
</template>

<style scoped>
.duplicate-overwrite { display: grid; gap: 10px; min-width: 0; padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-group); }
h3, h4, p { margin: 0; }
h3, h4 { font-size: 13px; color: var(--color-text); }
p { font-size: 12px; line-height: 1.5; color: var(--color-text-secondary); }
[role="alert"] { color: var(--color-danger); }
:deep(.unified-diff) { min-width: 0; tab-size: 4; }
.duplicate-overwrite__actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
