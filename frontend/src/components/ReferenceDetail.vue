<script setup lang="ts">
import type { Reference } from "../types/reference";
import BibtexExportPanel from "./BibtexExportPanel.vue";
import ReferenceActions from "./ReferenceActions.vue";
import AppIcon from "./AppIcon.vue";

defineProps<{
  reference: Reference | null;
  authenticated: boolean;
}>();

const emit = defineEmits<{
  updated: [reference: Reference];
  deleted: [referenceId: string];
  loginRequired: [];
}>();
</script>

<template>
  <section class="reference-detail">
    <div v-if="!reference" class="placeholder">
      <div class="state-icon" aria-hidden="true">
        <AppIcon name="journal-bookmark" />
      </div>
      <h2>Select a reference</h2>
      <p>Choose an item from the library to view its metadata and BibTeX.</p>
    </div>

    <template v-else>
      <header class="detail-header">
        <div>
          <h2>{{ reference.title || "Untitled reference" }}</h2>
        </div>
        <div class="detail-header__actions">
          <a
            v-if="reference.url"
            class="source-link"
            :href="reference.url"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>Open source</span>
            <AppIcon name="box-arrow-up-right" />
          </a>
          <ReferenceActions
            :reference="reference"
            :authenticated="authenticated"
            @updated="emit('updated', $event)"
            @deleted="emit('deleted', $event)"
            @login-required="emit('loginRequired')"
          />
        </div>
      </header>

      <div class="detail-section">
        <h3>Metadata</h3>
        <dl class="metadata-list">
          <div class="metadata-row">
            <dt>Authors</dt>
            <dd>{{ reference.authors.length > 0 ? reference.authors.join(", ") : "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>Year</dt>
            <dd>{{ reference.year ?? "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>Venue</dt>
            <dd>{{ reference.venue || "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>DOI</dt>
            <dd>{{ reference.doi || "Unknown" }}</dd>
          </div>

          <div class="metadata-row">
            <dt>BibTeX Key</dt>
            <dd>{{ reference.bibtexKey || "Unknown" }}</dd>
          </div>
        </dl>
      </div>

      <div
        v-if="reference.citationContexts?.length"
        class="detail-section citation-contexts"
      >
        <div class="detail-section__heading">
          <h3>Citation Contexts</h3>
          <span>{{ reference.citationContexts.length }}</span>
        </div>
        <ol class="citation-context-list">
          <li
            v-for="context in reference.citationContexts"
            :key="context.id"
          >
            <p
              v-if="context.sourcePaperTitle || context.sourceFileName"
              class="citation-context-source"
            >
              {{ context.sourcePaperTitle || context.sourceFileName }}
              <span
                v-if="
                  context.sourcePaperTitle &&
                  context.sourceFileName
                "
              >
                · {{ context.sourceFileName }}
              </span>
            </p>
            <blockquote>
              <span v-if="context.before" class="citation-context-muted">
                {{ context.before }}
              </span>
              <mark>{{ context.context }}</mark>
              <span v-if="context.after" class="citation-context-muted">
                {{ context.after }}
              </span>
            </blockquote>
          </li>
        </ol>
      </div>

      <div class="detail-section bibtex-detail">
        <h3>BibTeX</h3>
        <BibtexExportPanel
          v-if="reference.bibtex"
          :source="reference.bibtex"
          :citation-key="reference.bibtexKey"
        />
        <p v-else class="muted">BibTeX has not been reconstructed yet.</p>
      </div>
    </template>
  </section>
</template>
