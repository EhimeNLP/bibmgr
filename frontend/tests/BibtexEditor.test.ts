// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import BibtexEditor from "../src/components/BibtexEditor.vue";
import {
  countBibliographicEntries,
  extractBibliographicEntries,
  tokenizeBibtex,
} from "../src/utils/bibtexHighlight";

describe("BibTeX highlighting", () => {
  it("tokenizes syntax without changing the source text", () => {
    const bibtex = `% a comment
@article{demo2025,
  title = {A {Nested} Title},
  year = 2025,
  note = "Quoted value"
}`;
    const tokens = tokenizeBibtex(bibtex);

    expect(tokens.map((token) => token.value).join("")).toBe(bibtex);
    expect(tokens).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ kind: "comment" }),
        expect.objectContaining({ kind: "entry", value: "@article" }),
        expect.objectContaining({ kind: "key", value: "demo2025" }),
        expect.objectContaining({ kind: "field", value: "title" }),
        expect.objectContaining({ kind: "value", value: "{A {Nested} Title}" }),
        expect.objectContaining({ kind: "number", value: "2025" }),
      ]),
    );
  });

  it("counts bibliography entries while ignoring BibTeX directives", () => {
    expect(
      countBibliographicEntries(
        '@string{jmlr = "Journal of ML Research"}\n@article{demo, title={One}}',
      ),
    ).toBe(1);
    expect(
      countBibliographicEntries(
        "@article{one, title={One}}\n@book{two, title={Two}}",
      ),
    ).toBe(2);
  });

  it("extracts multiple complete entries without changing their contents", () => {
    const first = "@article{one, title={A {Nested} Title}}";
    const second = '@book(two, title="Two", year=2026)';
    const source = `% library metadata
@string{publisher = "Example Press"}
${first}

${second}`;

    expect(extractBibliographicEntries(source)).toEqual([first, second]);
  });

  it("keeps the textarea accessible and renders untrusted text safely", async () => {
    const untrusted = "@article{demo, title={<script>alert(1)</script>}}";
    const wrapper = mount(BibtexEditor, {
      props: {
        id: "safe-bibtex",
        modelValue: untrusted,
        accessibleLabel: "BibTeX entry",
      },
    });

    const mirror = wrapper.get(".bibtex-editor__highlight");
    const textarea = wrapper.get<HTMLTextAreaElement>("textarea");
    expect(mirror.attributes("aria-hidden")).toBe("true");
    expect(mirror.element.textContent).toContain(untrusted);
    expect(wrapper.find("script").exists()).toBe(false);
    expect(textarea.attributes("aria-label")).toBe("BibTeX entry");

    textarea.element.scrollTop = 36;
    textarea.element.scrollLeft = 12;
    await textarea.trigger("scroll");
    expect((mirror.element as HTMLElement).scrollTop).toBe(36);
    expect((mirror.element as HTMLElement).scrollLeft).toBe(12);

    await textarea.setValue("@book{next, title={Next}}");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([
      "@book{next, title={Next}}",
    ]);
  });
});
