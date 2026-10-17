<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from "vue";
import type { DuplicateFinding } from "../api/duplicates";
import { getReference } from "../api/references";
import { bibtexTextForDisplay } from "../utils/bibtexDisplay";

const props = defineProps<{ findings: DuplicateFinding[]; confirmationToken?: string; confirmLabel?: string; busy?: boolean; canRemove?: boolean; canOverwrite?: boolean }>();
defineEmits<{ confirm: []; remove: [indices: number[]]; overwrite: [finding: DuplicateFinding] }>();
const panel = ref<HTMLElement | null>(null);
async function reveal() {
  await nextTick();
  if (!panel.value) return;
  panel.value.focus({ preventScroll: true });
  panel.value.scrollIntoView({ block: "start", inline: "nearest", behavior: "instant" });
}
defineExpose({ reveal });
const groups = computed(() => {
  const result = new Map<number, DuplicateFinding[]>();
  for (const finding of props.findings) {
    const group = result.get(finding.incoming_index) ?? [];
    group.push(finding);
    result.set(finding.incoming_index, group);
  }
  return [...result].sort(([a], [b]) => a - b);
});
// Keep an earlier input representative for each batch match, including non-transitive matches.
const bulkIndices = computed(() => {
  const removed = new Set<number>();
  for (const [index, findings] of groups.value) {
    if (findings.some(finding => finding.action === "reject" &&
      (finding.existing || !removed.has(finding.candidate_index)))) removed.add(index);
  }
  return [...removed];
});
type Preview = { open: boolean; loading: boolean; source?: string; error?: string };
const previews = reactive<Record<string, Preview>>({});
watch(() => props.findings, () => {
  for (const id of Object.keys(previews)) delete previews[id];
});
async function toggleReference(id: string, key: string) {
  previews[key] ??= { open: false, loading: false };
  const preview = previews[key]!;
  preview.open = !preview.open;
  if (!preview.open || preview.loading || preview.source !== undefined) return;
  preview.loading = true;
  preview.error = undefined;
  try { preview.source = (await getReference(id)).bibtex || "No BibTeX available."; }
  catch (failure) { preview.error = failure instanceof Error ? failure.message : "Could not load reference."; }
  finally { preview.loading = false; }
}
const labels: Record<string, string> = {
  citation_key: "Citation key", title: "Title", doi: "DOI", arxiv: "arXiv ID", arxiv_family: "arXiv work",
  authors: "Authors", year: "Year", venue: "Venue", volume: "Volume", number: "Issue", pages: "Pages",
};
</script>

<template>
  <section v-if="findings.length" ref="panel" class="duplicate-review" aria-label="Duplicate review" tabindex="-1">
    <div class="duplicate-review__header">
      <div>
        <h3>Related references <span>{{ groups.length }}</span></h3>
        <p v-if="confirmationToken">Review these matches before saving.</p>
        <p v-else-if="findings.some(f => f.action === 'reject')">Resolve duplicate entries before saving.</p>
        <p v-else>The following references share identifying information.</p>
        <p v-if="canRemove">Remove entries from this input to keep the existing references.</p>
        <p v-if="canOverwrite">Or use the input entry to overwrite a stored reference or replace a matching input entry.</p>
      </div>
      <button v-if="canRemove && bulkIndices.length" type="button" class="button-secondary" :disabled="busy" @click="$emit('remove', bulkIndices)">
        Remove all duplicates ({{ bulkIndices.length }})
      </button>
    </div>
    <article v-for="[entryIndex, matches] in groups" :key="entryIndex" class="duplicate-review__entry">
      <div class="duplicate-review__entry-header">
        <h4>Input entry {{ entryIndex + 1 }}</h4>
        <button v-if="canRemove" type="button" class="button-secondary" :disabled="busy" :aria-label="`Remove input entry ${entryIndex + 1}`" @click="$emit('remove', [entryIndex])">Remove from input</button>
      </div>
      <div v-for="(finding, index) in matches" :key="index" class="duplicate-review__match">
        <div class="duplicate-review__metadata">
          <span>{{ finding.existing ? 'Stored reference' : `Matches input entry ${finding.candidate_index + 1}` }}</span>
          <span :class="{ 'duplicate-review__blocking': finding.action === 'reject' }">{{ finding.action === 'reject' ? 'Duplicate' : 'Possible match' }}</span>
        </div>
        <h5>{{ finding.title || finding.citation_key || 'Untitled reference' }}</h5>
        <code v-if="finding.citation_key">{{ finding.citation_key }}</code>
        <details>
          <summary>Compare fields</summary>
          <div class="duplicate-review__table">
            <table>
              <thead><tr><th scope="col">Field</th><th scope="col">Input</th><th scope="col">Candidate</th><th scope="col">Comparison</th></tr></thead>
              <tbody>
                <tr v-for="field in finding.comparison.fields" :key="field.field">
                  <th scope="row">{{ labels[field.field] || field.field }}</th>
                  <td>{{ (['title', 'venue'].includes(field.field) ? field.left.map(bibtexTextForDisplay) : field.left).join('; ') || '—' }}</td><td>{{ (['title', 'venue'].includes(field.field) ? field.right.map(bibtexTextForDisplay) : field.right).join('; ') || '—' }}</td>
                  <td>{{ field.agreement === 'missing' ? 'Insufficient information' : field.agreement === 'match' ? 'Matches' : 'Differs' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
        <template v-if="finding.reference_id">
          <button type="button" class="button-secondary" :aria-expanded="Boolean(previews[`${entryIndex}-${index}`]?.open)" @click="toggleReference(finding.reference_id, `${entryIndex}-${index}`)">{{ previews[`${entryIndex}-${index}`]?.open ? 'Hide existing BibTeX' : 'View existing BibTeX' }}</button>
          <div v-if="previews[`${entryIndex}-${index}`]?.open" class="duplicate-review__preview">
            <p v-if="previews[`${entryIndex}-${index}`]?.loading" role="status">Loading BibTeX…</p>
            <p v-else-if="previews[`${entryIndex}-${index}`]?.error" role="alert">{{ previews[`${entryIndex}-${index}`]?.error }}</p>
            <pre v-else>{{ previews[`${entryIndex}-${index}`]?.source }}</pre>
          </div>
        </template>
        <button v-if="canOverwrite && (!finding.existing || finding.reference_id)" type="button" class="button-secondary duplicate-review__overwrite" :disabled="busy" @click="$emit('overwrite', finding)">
          {{ finding.existing ? 'Overwrite existing reference…' : `Replace input entry ${finding.candidate_index + 1} with this entry` }}
        </button>
      </div>
    </article>
    <button v-if="confirmationToken" type="button" class="button-secondary" :disabled="busy" @click="$emit('confirm')">{{ confirmLabel || 'Save as a separate reference' }}</button>
  </section>
</template>

<style scoped>
.duplicate-review { display: grid; gap: 10px; padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-group); background: var(--color-surface); overflow-wrap: anywhere; }
.duplicate-review__header, .duplicate-review__entry-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
h3, h4, h5, p { margin: 0; }
h3, h4 { color: var(--color-text); font-size: 12px; font-weight: 650; }
h3 span { margin-left: 5px; color: var(--color-text-muted); font-weight: 500; }
p { margin-top: 5px; color: var(--color-text-secondary); font-size: 11.5px; line-height: 1.5; }
.duplicate-review__entry { min-width: 0; border: 1px solid var(--color-border); border-radius: var(--radius-control); overflow: hidden; }
.duplicate-review__entry-header { padding: 10px; align-items: center; background: var(--color-fill); }
.duplicate-review__match { padding: 12px; }
.duplicate-review__match + .duplicate-review__match { border-top: 1px solid var(--color-border); }
.duplicate-review__metadata { display: flex; flex-wrap: wrap; gap: 8px; color: var(--color-text-muted); font-size: 10.5px; }
.duplicate-review__blocking { color: var(--color-danger); }
h5 { margin-top: 6px; color: var(--color-text); font-size: 13px; line-height: 1.5; font-weight: 600; }
code { color: var(--color-text-muted); font-size: 10.5px; }
details { margin-block: 10px; }
summary { width: fit-content; cursor: pointer; color: var(--color-text-secondary); font-size: 11.5px; }
summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.duplicate-review__table { overflow-x: auto; margin-top: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 11px; color: var(--color-text-secondary); }
th, td { padding: 7px; border-bottom: 1px solid var(--color-border); text-align: left; vertical-align: top; min-width: 75px; }
.button-secondary { min-height: 30px; font-size: 10.5px; flex-shrink: 0; }
.duplicate-review__overwrite { display: block; margin-top: 8px; white-space: normal; }
.duplicate-review__preview { margin-top: 8px; padding: 10px; border-radius: var(--radius-control); background: var(--color-fill); }
pre { margin: 0; padding: 0; background: transparent; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
@media (max-width: 540px) { .duplicate-review__header { flex-direction: column; } }
</style>
