<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { tokenizeBibtex } from "../utils/bibtexHighlight";

const MAX_HIGHLIGHT_LENGTH = 200_000;

const props = withDefaults(
  defineProps<{
    id: string;
    modelValue: string;
    accessibleLabel: string;
    placeholder?: string;
    rows?: number;
    disabled?: boolean;
    describedBy?: string;
  }>(),
  {
    placeholder: "",
    rows: 8,
    disabled: false,
    describedBy: undefined,
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const textarea = ref<HTMLTextAreaElement | null>(null);
const highlightLayer = ref<HTMLElement | null>(null);
const isComposing = ref(false);
const tokens = computed(() =>
  props.modelValue.length > MAX_HIGHLIGHT_LENGTH
    ? [{ kind: "plain" as const, value: props.modelValue }]
    : tokenizeBibtex(props.modelValue),
);

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
      :class="`bibtex-token bibtex-token--${token.kind}`"
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
