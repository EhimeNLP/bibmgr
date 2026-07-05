<script setup lang="ts">
import type { Reference } from "../types/reference";

defineProps<{
  reference: Reference | null;
}>();

async function copyText(text?: string) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
}
</script>

<template>
  <section class="reference-detail">
    <div v-if="!reference" class="placeholder">
      Select a reference to view details.
    </div>

    <template v-else>
      <h2>{{ reference.title || "Untitled reference" }}</h2>

      <div class="detail-section">
        <h3>Metadata</h3>
        <dl>
          <dt>Authors</dt>
          <dd>{{ reference.authors.length > 0 ? reference.authors.join(", ") : "Unknown" }}</dd>

          <dt>Year</dt>
          <dd>{{ reference.year ?? "Unknown" }}</dd>

          <dt>Venue</dt>
          <dd>{{ reference.venue || "Unknown" }}</dd>

          <dt>DOI</dt>
          <dd>{{ reference.doi || "Unknown" }}</dd>

          <dt>BibTeX Key</dt>
          <dd>{{ reference.bibtexKey || "Unknown" }}</dd>
        </dl>
      </div>

      <div class="detail-section">
        <div class="section-header">
          <h3>BibTeX</h3>
          <button
            v-if="reference.bibtex"
            type="button"
            @click="copyText(reference.bibtex)"
          >
            Copy
          </button>
        </div>

        <pre v-if="reference.bibtex"><code>{{ reference.bibtex }}</code></pre>
        <p v-else class="muted">BibTeX has not been reconstructed yet.</p>
      </div>

      <div class="detail-section">
        <h3>Citation Contexts</h3>

        <div
          v-if="reference.citationContexts && reference.citationContexts.length > 0"
          class="contexts"
        >
          <article
            v-for="context in reference.citationContexts"
            :key="context.id"
            class="context-card"
          >
            <p v-if="context.sourcePaperTitle" class="context-source">
              {{ context.sourcePaperTitle }}
            </p>
            <p v-if="context.before" class="muted">{{ context.before }}</p>
            <p class="context-main">{{ context.context }}</p>
            <p v-if="context.after" class="muted">{{ context.after }}</p>
          </article>
        </div>

        <p v-else class="muted">
          Citation contexts have not been extracted yet.
        </p>
      </div>
    </template>
  </section>
</template>
