<script setup lang="ts">
import { computed } from "vue";
import { tokenizeBibtexForHighlight } from "../utils/bibtexHighlight";

const props = withDefaults(
  defineProps<{
    source: string;
    accessibleLabel?: string;
    testId?: string;
  }>(),
  {
    accessibleLabel: "BibTeX source",
    testId: undefined,
  },
);

const tokens = computed(() => tokenizeBibtexForHighlight(props.source));
</script>

<template>
  <pre
    class="bibtex-code-block"
    :aria-label="accessibleLabel"
    :data-testid="testId"
    tabindex="0"
  ><code><span
    v-for="(token, index) in tokens"
    :key="`${index}-${token.kind}`"
    :class="`bibtex-token bibtex-token--${token.kind}`"
  >{{ token.value }}</span></code></pre>
</template>
