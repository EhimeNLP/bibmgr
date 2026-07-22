<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { analyzeBibtex, applyBibtexFixes } from "../api/bibtex";
import type {
  BibtexAnalysisResult,
  BibtexDiagnostic,
  BibtexFix,
} from "../types/bibtex";

const props = withDefaults(
  defineProps<{
    source: string;
    disabled?: boolean;
    profile?: string;
    debounceMs?: number;
    realtime?: boolean;
  }>(),
  {
    disabled: false,
    profile: "laboratory",
    debounceMs: 350,
    realtime: true,
  },
);

const emit = defineEmits<{
  "update:source": [source: string];
  "update:diagnostics": [diagnostics: BibtexDiagnostic[]];
  fixed: [fixId: string];
}>();

const analysis = ref<BibtexAnalysisResult | null>(null);
const analyzedSource = ref("");
const analyzedProfile = ref("");
const isChecking = ref(false);
const applyingFixId = ref<string | null>(null);
const error = ref<string | null>(null);
let sourceGeneration = 0;
let requestGeneration = 0;
let checkTimer: ReturnType<typeof setTimeout> | undefined;
let checkController: AbortController | null = null;
let appliedSourcePending: string | null = null;
let hasObservedSource = false;
let observedSource = "";
let observedProfile = "";

watch(
  [() => props.source, () => props.profile],
  ([source, profile]) => {
    const isInitial = !hasObservedSource;
    if (
      !isInitial &&
      source === observedSource &&
      profile === observedProfile
    ) {
      return;
    }
    hasObservedSource = true;
    observedSource = source;
    observedProfile = profile;
    sourceGeneration += 1;
    cancelScheduledCheck();
    invalidatePendingCheck();
    error.value = null;

    if (source === appliedSourcePending) {
      appliedSourcePending = null;
      emit("update:diagnostics", analysis.value?.diagnostics ?? []);
      return;
    }

    if (!isInitial) emit("update:diagnostics", []);
    if (!source.trim()) {
      analysis.value = null;
      analyzedSource.value = "";
      analyzedProfile.value = "";
      return;
    }

    if (props.realtime) {
      checkTimer = setTimeout(() => {
        checkTimer = undefined;
        void runCheck();
      }, Math.max(0, props.debounceMs));
    }
  },
  { flush: "sync", immediate: true },
);

onBeforeUnmount(() => {
  cancelScheduledCheck();
  invalidatePendingCheck();
});

const isCurrent = computed(
  () =>
    analysis.value !== null &&
    analyzedSource.value === props.source &&
    analyzedProfile.value === props.profile,
);
const diagnostics = computed(() =>
  isCurrent.value ? (analysis.value?.diagnostics ?? []) : [],
);
const fixes = computed(() =>
  isCurrent.value ? (analysis.value?.available_fixes ?? []) : [],
);
const blockingCount = computed(
  () => diagnostics.value.filter((diagnostic) => diagnostic.blocking).length,
);
const statusMessage = computed(() => {
  const count = diagnostics.value.length;
  if (count === 0) return "No diagnostics. This source passes the selected lint profile.";
  const diagnosticLabel = count === 1 ? "1 diagnostic" : `${count} diagnostics`;
  if (blockingCount.value === 0) return `${diagnosticLabel}; none are blocking.`;
  const blockingLabel =
    blockingCount.value === 1
      ? "1 is blocking"
      : `${blockingCount.value} are blocking`;
  return `${diagnosticLabel}; ${blockingLabel}.`;
});

function cancelScheduledCheck(): void {
  if (checkTimer === undefined) return;
  clearTimeout(checkTimer);
  checkTimer = undefined;
}

function invalidatePendingCheck(): void {
  requestGeneration += 1;
  checkController?.abort();
  checkController = null;
  isChecking.value = false;
}

function isAbortError(cause: unknown): boolean {
  return (
    typeof cause === "object" &&
    cause !== null &&
    "name" in cause &&
    cause.name === "AbortError"
  );
}

async function runCheck(): Promise<void> {
  if (!props.source.trim() || props.disabled) return;

  cancelScheduledCheck();
  invalidatePendingCheck();

  const source = props.source;
  const profile = props.profile;
  hasObservedSource = true;
  observedSource = source;
  observedProfile = profile;
  const requestedSourceGeneration = sourceGeneration;
  const requestedGeneration = requestGeneration;
  const controller = new AbortController();
  checkController = controller;
  isChecking.value = true;
  error.value = null;
  try {
    const nextAnalysis = await analyzeBibtex(
      {
        source,
        profile,
        mode: "tolerant",
      },
      { signal: controller.signal },
    );
    if (
      requestedGeneration !== requestGeneration ||
      requestedSourceGeneration !== sourceGeneration ||
      props.source !== source ||
      props.profile !== profile
    ) {
      return;
    }

    analysis.value = nextAnalysis;
    analyzedSource.value = source;
    analyzedProfile.value = profile;
    await nextTick();
    if (
      requestedGeneration !== requestGeneration ||
      requestedSourceGeneration !== sourceGeneration ||
      props.source !== source ||
      props.profile !== profile
    ) {
      return;
    }
    emit("update:diagnostics", nextAnalysis.diagnostics);
  } catch (cause) {
    if (
      requestedGeneration !== requestGeneration ||
      requestedSourceGeneration !== sourceGeneration ||
      isAbortError(cause)
    ) {
      return;
    }
    analysis.value = null;
    analyzedSource.value = source;
    analyzedProfile.value = profile;
    emit("update:diagnostics", []);
    error.value =
      cause instanceof Error ? cause.message : "Could not lint this BibTeX source.";
  } finally {
    if (requestedGeneration === requestGeneration) {
      checkController = null;
      isChecking.value = false;
    }
  }
}

async function check(): Promise<void> {
  // A click may arrive in the same tick as a parent v-model update. Let the
  // source watcher invalidate the previous generation before starting this one.
  await nextTick();
  await runCheck();
}

async function applyFix(fix: BibtexFix): Promise<void> {
  const currentAnalysis = analysis.value;
  if (
    !isCurrent.value ||
    currentAnalysis === null ||
    props.disabled ||
    fix.applicability === "unsafe" ||
    applyingFixId.value
  ) {
    return;
  }
  if (
    fix.applicability === "requires_confirmation" &&
    !window.confirm(`Apply “${fix.title}”? This may change bibliographic meaning.`)
  ) {
    return;
  }

  const source = props.source;
  const requestSourceGeneration = sourceGeneration;
  const isRequestSourceCurrent = () =>
    sourceGeneration === requestSourceGeneration && props.source === source;
  applyingFixId.value = fix.id;
  error.value = null;
  try {
    const applied = await applyBibtexFixes({
      source,
      source_revision: currentAnalysis.source_revision,
      fix_ids: [fix.id],
      profile: props.profile,
    });

    if (!isRequestSourceCurrent()) return;

    const nextAnalysis =
      applied.analysis ??
      (await analyzeBibtex({
        source: applied.source,
        profile: props.profile,
        mode: "tolerant",
      }));

    if (!isRequestSourceCurrent()) return;

    analyzedSource.value = applied.source;
    analyzedProfile.value = props.profile;
    analysis.value = nextAnalysis;
    appliedSourcePending = applied.source === props.source ? null : applied.source;
    emit("update:diagnostics", nextAnalysis.diagnostics);
    emit("update:source", applied.source);
    emit("fixed", fix.id);
  } catch (cause) {
    if (isRequestSourceCurrent()) {
      error.value =
        cause instanceof Error ? cause.message : "Could not apply this BibTeX fix.";
    }
  } finally {
    applyingFixId.value = null;
  }
}

function fixButtonLabel(fix: BibtexFix): string {
  if (applyingFixId.value === fix.id) return "Applying…";
  if (fix.applicability === "unsafe") return "Manual fix only";
  if (fix.applicability === "requires_confirmation") return "Review and apply";
  return "Apply fix";
}

defineExpose({ check });
</script>

<template>
  <section class="bibtex-lint" aria-label="BibTeX lint results">
    <div class="bibtex-lint__toolbar">
      <div>
        <strong>Shared BibTeX lint</strong>
        <span>Uses the same Rust rules as the CLI.</span>
      </div>
      <button
        type="button"
        class="button-secondary bibtex-lint__check"
        :disabled="disabled || !source.trim() || isChecking"
        :aria-busy="isChecking"
        @click="check"
      >
        {{ isChecking ? "Checking…" : "Check BibTeX" }}
      </button>
    </div>

    <p v-if="error" class="bibtex-lint__error" role="alert">
      {{ error }}
    </p>
    <p
      v-else-if="analysis && !isCurrent"
      class="bibtex-lint__stale"
      role="status"
    >
      Source changed after the last check. Check again before applying a fix.
    </p>

    <template v-else-if="isCurrent">
      <p
        class="bibtex-lint__summary"
        :class="{ 'is-blocking': blockingCount > 0 }"
        role="status"
      >
        {{ statusMessage }}
      </p>

      <ul v-if="diagnostics.length" class="bibtex-diagnostics" aria-label="Diagnostics">
        <li
          v-for="diagnostic in diagnostics"
          :key="diagnostic.id"
          class="bibtex-diagnostic"
          :class="`is-${diagnostic.severity}`"
        >
          <div class="bibtex-diagnostic__heading">
            <code>{{ diagnostic.code }}</code>
            <span>{{ diagnostic.severity }}</span>
            <strong v-if="diagnostic.blocking">Blocking</strong>
          </div>
          <p>{{ diagnostic.message }}</p>
          <small v-if="diagnostic.primary_location">
            UTF-8 bytes {{ diagnostic.primary_location.range.start }}–{{ diagnostic.primary_location.range.end }}
          </small>
          <ul
            v-if="diagnostic.related_locations.length"
            class="bibtex-diagnostic__related"
            aria-label="Related locations"
          >
            <li
              v-for="(related, index) in diagnostic.related_locations"
              :key="`${diagnostic.id}-related-${index}`"
            >
              <span>{{ related.message }}</span>
              <small>
                UTF-8 bytes {{ related.location.range.start }}–{{ related.location.range.end }}
              </small>
            </li>
          </ul>
          <ul
            v-if="diagnostic.notes.length"
            class="bibtex-diagnostic__notes"
            aria-label="Diagnostic notes"
          >
            <li v-for="(note, index) in diagnostic.notes" :key="`${diagnostic.id}-note-${index}`">
              {{ note }}
            </li>
          </ul>
        </li>
      </ul>

      <ul v-if="fixes.length" class="bibtex-fixes" aria-label="Available fixes">
        <li v-for="fix in fixes" :key="fix.id">
          <div>
            <strong>{{ fix.title }}</strong>
            <span>{{ fix.applicability.replaceAll("_", " ") }}</span>
          </div>
          <button
            type="button"
            class="button-secondary"
            :disabled="
              disabled ||
              Boolean(applyingFixId) ||
              fix.applicability === 'unsafe'
            "
            :aria-busy="applyingFixId === fix.id"
            @click="applyFix(fix)"
          >
            {{ fixButtonLabel(fix) }}
          </button>
        </li>
      </ul>
    </template>
  </section>
</template>
