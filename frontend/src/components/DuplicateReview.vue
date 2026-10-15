<script setup lang="ts">
import { ref } from "vue";
import type { DuplicateFinding } from "../api/duplicates";
import { getReference } from "../api/references";

defineProps<{ findings: DuplicateFinding[]; confirmationToken?: string; busy?: boolean }>();
defineEmits<{ confirm: [] }>();
const source = ref("");
const error = ref("");
async function showReference(id: string) {
  source.value = "";
  error.value = "";
  try { source.value = (await getReference(id)).bibtex ?? ""; }
  catch (failure) { error.value = failure instanceof Error ? failure.message : "Could not load reference."; }
}
const labels: Record<string, string> = {
  citation_key: "Citation key", title: "Title", doi: "DOI", arxiv: "arXiv ID", arxiv_family: "arXiv work",
  authors: "Authors", year: "Year", venue: "Venue", volume: "Volume", number: "Issue", pages: "Pages",
};
</script>

<template>
  <section v-if="findings.length" class="duplicate-review" aria-label="Duplicate review" aria-live="polite">
    <h3>Related references</h3>
    <p v-if="confirmationToken">Review these matches. Continue only if you intend to keep a separate reference.</p>
    <p v-else-if="findings.some(f => f.action === 'reject')">Use or edit the existing reference instead of adding a duplicate.</p>
    <p v-else>The following references share identifying information.</p>
    <article v-for="(finding, index) in findings" :key="index">
      <h4>{{ finding.title || finding.citation_key || 'Untitled reference' }}</h4>
      <p>Input entry {{ finding.incoming_index + 1 }} · {{ finding.existing ? 'Stored reference' : `Input entry ${finding.candidate_index + 1}` }} · {{ finding.citation_key }}</p>
      <details>
        <summary>Compare fields</summary>
        <table>
          <thead><tr><th>Field</th><th>Input</th><th>Candidate</th><th>Comparison</th></tr></thead>
          <tbody>
            <tr v-for="field in finding.comparison.fields" :key="field.field">
              <th>{{ labels[field.field] || field.field }}</th>
              <td>{{ field.left.join('; ') || '—' }}</td><td>{{ field.right.join('; ') || '—' }}</td>
              <td>{{ field.agreement === 'missing' ? 'Insufficient information' : field.agreement === 'match' ? 'Matches' : 'Differs' }}</td>
            </tr>
          </tbody>
        </table>
      </details>
      <button v-if="finding.reference_id" type="button" class="button-secondary" @click="showReference(finding.reference_id)">View existing BibTeX</button>
    </article>
    <pre v-if="source">{{ source }}</pre>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="confirmationToken" type="button" class="button-secondary" :disabled="busy" @click="$emit('confirm')">Save as a separate reference</button>
  </section>
</template>

<style scoped>
.duplicate-review { margin-block: 1rem; padding: 1rem; border: 1px solid currentColor; border-radius: .5rem; overflow-wrap: anywhere; }
article + article { margin-top: 1rem; }
details { overflow-x: auto; margin-block: .5rem; }
th, td { padding: .4rem; text-align: left; vertical-align: top; }
pre { white-space: pre-wrap; }
</style>
