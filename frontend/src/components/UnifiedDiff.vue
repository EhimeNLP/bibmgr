<script setup lang="ts">
import { computed } from "vue";
import {
  createJsonDiff,
  createTextDiff,
} from "../utils/textDiff";
import AppIcon from "./AppIcon.vue";

type DiffValue = string | Record<string, unknown> | null;

const props = withDefaults(
  defineProps<{
    before: DiffValue;
    after: DiffValue;
    beforeLabel?: string;
    afterLabel?: string;
    accessibleLabel?: string;
    format?: "text" | "json";
  }>(),
  {
    beforeLabel: "Before",
    afterLabel: "After",
    accessibleLabel: "Text changes",
    format: "text",
  },
);

const diff = computed(() =>
  props.format === "json"
    ? createJsonDiff(props.before, props.after)
    : createTextDiff(
        typeof props.before === "string" ? props.before : "",
        typeof props.after === "string" ? props.after : "",
      ),
);
</script>

<template>
  <section class="unified-diff" role="region" :aria-label="accessibleLabel">
    <header class="unified-diff__header">
      <span>
        <AppIcon name="file-diff" />
        {{ beforeLabel }} → {{ afterLabel }}
      </span>
      <span class="unified-diff__summary">
        <strong class="addition">+{{ diff.additions }}</strong>
        <strong class="deletion">−{{ diff.deletions }}</strong>
      </span>
    </header>
    <div
      class="unified-diff__viewport"
      tabindex="0"
      :aria-label="`${accessibleLabel} lines`"
    >
      <table v-if="diff.rows.length > 0">
        <caption class="sr-only">
          {{ accessibleLabel }}. {{ diff.additions }} added lines and
          {{ diff.deletions }} removed lines.
        </caption>
        <colgroup>
          <col class="unified-diff__line-number-column" />
          <col class="unified-diff__line-number-column" />
          <col class="unified-diff__marker-column" />
          <col />
        </colgroup>
        <tbody>
          <tr
            v-for="(row, index) in diff.rows"
            :key="`${index}-${row.kind}`"
            :class="`is-${row.kind}`"
          >
            <td class="unified-diff__line-number" aria-hidden="true">
              {{ row.oldLine ?? "" }}
            </td>
            <td class="unified-diff__line-number" aria-hidden="true">
              {{ row.newLine ?? "" }}
            </td>
            <td class="unified-diff__marker" aria-hidden="true">
              {{ row.marker }}
            </td>
            <td class="unified-diff__code">
              <code>{{ row.text || "\u00a0" }}</code>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="unified-diff__empty">No textual changes.</p>
    </div>
  </section>
</template>

<style scoped>
.unified-diff {
  overflow: hidden;
  border: 0.5px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
}

.unified-diff__header {
  display: flex;
  min-height: 36px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 10px;
  border-bottom: 0.5px solid var(--color-border);
  background: var(--color-fill);
  color: var(--color-text-secondary);
  font-size: 10.5px;
  font-weight: 600;
}

.unified-diff__header > span:first-child {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
}

.unified-diff__header :deep(.app-icon) {
  font-size: 13px;
}

.unified-diff__summary {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
  font-family: "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
  font-size: 10px;
}

.unified-diff__summary strong {
  font-weight: 650;
}

.unified-diff__summary .addition {
  color: var(--color-diff-add-text);
}

.unified-diff__summary .deletion {
  color: var(--color-diff-delete-text);
}

.unified-diff__viewport {
  max-height: 360px;
  overflow: auto;
}

.unified-diff__viewport:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
}

.unified-diff table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}

.unified-diff td {
  padding: 0;
  border: 0;
  vertical-align: top;
}

.unified-diff__line-number-column {
  width: 28px;
}

.unified-diff__marker-column {
  width: 14px;
}

.unified-diff__line-number {
  padding: 1px 3px !important;
  border-right: 0.5px solid var(--color-border) !important;
  background: var(--color-fill);
  color: var(--color-text-secondary);
  font-family: "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
  font-size: 9px;
  font-variant-numeric: tabular-nums;
  line-height: 1.55;
  text-align: right;
  user-select: none;
}

.unified-diff__marker {
  padding: 1px !important;
  color: var(--color-text-secondary);
  font-family: "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
  font-size: 10px;
  line-height: 1.55;
  text-align: center;
  user-select: none;
}

.unified-diff__code {
  padding: 1px 10px 1px 2px !important;
  color: var(--color-text);
  font-family: "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
  font-size: 10px;
  line-height: 1.55;
  white-space: pre;
}

.unified-diff__code code {
  font: inherit;
}

.unified-diff tr.is-addition td {
  background: var(--color-diff-add-bg);
}

.unified-diff tr.is-addition .unified-diff__line-number,
.unified-diff tr.is-addition .unified-diff__marker {
  background: var(--color-diff-add-gutter);
  color: var(--color-diff-add-text);
}

.unified-diff tr.is-deletion td {
  background: var(--color-diff-delete-bg);
}

.unified-diff tr.is-deletion .unified-diff__line-number,
.unified-diff tr.is-deletion .unified-diff__marker {
  background: var(--color-diff-delete-gutter);
  color: var(--color-diff-delete-text);
}

.unified-diff__empty {
  margin: 0;
  padding: 20px;
  color: var(--color-text-muted);
  font-size: 11px;
  text-align: center;
}

</style>
