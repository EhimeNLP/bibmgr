<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import type { BibtexDiagnostic, DiagnosticSeverity } from "../types/bibtex";
import { utf8ByteRangeToUtf16Range } from "../utils/bibtexDiagnostics";
import {
  tokenizeBibtex,
  tokenizeBibtexForHighlight,
} from "../utils/bibtexHighlight";

const props = withDefaults(
  defineProps<{
    id: string;
    modelValue: string;
    accessibleLabel: string;
    placeholder?: string;
    rows?: number;
    disabled?: boolean;
    describedBy?: string;
    diagnostics?: BibtexDiagnostic[];
  }>(),
  {
    placeholder: "",
    rows: 8,
    disabled: false,
    describedBy: undefined,
    diagnostics: () => [],
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const textarea = ref<HTMLTextAreaElement | null>(null);
const highlightLayer = ref<HTMLElement | null>(null);
const isComposing = ref(false);
type DiagnosticRange = {
  id: string;
  message: string;
  severity: DiagnosticSeverity;
  start: number;
  end: number;
};
type RenderToken = {
  kind: ReturnType<typeof tokenizeBibtex>[number]["kind"];
  value: string;
  diagnosticIds: string[];
  diagnosticMessages: string[];
  diagnosticSeverity?: DiagnosticSeverity;
};

const diagnosticRanges = computed<DiagnosticRange[]>(() =>
  props.diagnostics.flatMap((diagnostic) => {
    const sourceId = diagnostic.primary_location?.source_id;
    const locations = [
      ...(diagnostic.primary_location ? [diagnostic.primary_location] : []),
      ...diagnostic.related_locations
        .filter((related) => sourceId && related.location.source_id === sourceId)
        .map((related) => related.location),
    ];
    return locations.flatMap((location) => {
      const range = utf8ByteRangeToUtf16Range(props.modelValue, location.range);
      return range.start < range.end
        ? [
            {
              id: diagnostic.id,
              message: diagnostic.message,
              severity: diagnostic.severity,
              ...range,
            },
          ]
        : [];
    });
  }),
);
const tokens = computed<RenderToken[]>(() => {
  const syntaxTokens = tokenizeBibtexForHighlight(props.modelValue);
  return decorateTokens(syntaxTokens, diagnosticRanges.value);
});

const severityRank: Record<DiagnosticSeverity, number> = {
  error: 3,
  warning: 2,
  information: 1,
  hint: 0,
};

function decorateTokens(
  syntaxTokens: ReturnType<typeof tokenizeBibtex>,
  ranges: DiagnosticRange[],
): RenderToken[] {
  const rendered: RenderToken[] = [];
  let tokenStart = 0;

  for (const token of syntaxTokens) {
    const tokenEnd = tokenStart + token.value.length;
    const overlapping = ranges.filter(
      (range) => range.start < tokenEnd && tokenStart < range.end,
    );
    const boundaries = Array.from(
      new Set([
        tokenStart,
        tokenEnd,
        ...overlapping.flatMap((range) => [
          Math.max(tokenStart, range.start),
          Math.min(tokenEnd, range.end),
        ]),
      ]),
    ).sort((left, right) => left - right);

    for (let index = 0; index < boundaries.length - 1; index += 1) {
      const start = boundaries[index];
      const end = boundaries[index + 1];
      if (start === undefined || end === undefined || start >= end) continue;

      const active = overlapping.filter(
        (range) => range.start < end && start < range.end,
      );
      const mostSevere = active.reduce<DiagnosticSeverity | undefined>(
        (current, range) =>
          current === undefined || severityRank[range.severity] > severityRank[current]
            ? range.severity
            : current,
        undefined,
      );
      rendered.push({
        kind: token.kind,
        value: token.value.slice(start - tokenStart, end - tokenStart),
        diagnosticIds: [...new Set(active.map((range) => range.id))],
        diagnosticMessages: [...new Set(active.map((range) => range.message))],
        diagnosticSeverity: mostSevere,
      });
    }
    tokenStart = tokenEnd;
  }

  return rendered;
}

function onInput(event: Event) {
  emit("update:modelValue", (event.target as HTMLTextAreaElement).value);
  void nextTick(syncScroll);
}

function syncScroll() {
  if (!textarea.value || !highlightLayer.value) return;
  highlightLayer.value.scrollTop = textarea.value.scrollTop;
  highlightLayer.value.scrollLeft = textarea.value.scrollLeft;
}
</script>

<template>
  <div class="bibtex-editor" :class="{ 'is-composing': isComposing }">
    <pre
      ref="highlightLayer"
      class="bibtex-editor__highlight"
      aria-hidden="true"
    ><code><template v-if="modelValue"><span
      v-for="(token, index) in tokens"
      :key="`${index}-${token.kind}`"
      :class="[
        `bibtex-token bibtex-token--${token.kind}`,
        token.diagnosticSeverity &&
          `bibtex-diagnostic-range bibtex-diagnostic-range--${token.diagnosticSeverity}`,
      ]"
      :data-diagnostic-ids="token.diagnosticIds.length ? token.diagnosticIds.join(' ') : undefined"
      :title="token.diagnosticMessages.length ? token.diagnosticMessages.join('\n') : undefined"
    >{{ token.value }}</span></template><span
      v-else
      class="bibtex-editor__placeholder"
    >{{ placeholder }}</span><span class="bibtex-editor__sentinel">&#8203;</span></code></pre>
    <textarea
      :id="id"
      ref="textarea"
      :value="modelValue"
      :rows="rows"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-label="accessibleLabel"
      :aria-describedby="describedBy"
      autocomplete="off"
      autocapitalize="off"
      spellcheck="false"
      @input="onInput"
      @scroll="syncScroll"
      @compositionstart="isComposing = true"
      @compositionend="isComposing = false"
    />
  </div>
</template>
