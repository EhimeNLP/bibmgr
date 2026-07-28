// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ReferenceCard from "../src/components/ReferenceCard.vue";
import type { Reference } from "../src/types/reference";

describe("ReferenceCard", () => {
  it("shows only the title, authors, and year from reference metadata", () => {
    const reference: Reference = {
      id: "reference-1",
      title: "A useful paper",
      authors: ["Ada Lovelace", "Alan Turing"],
      year: 2024,
      venue: "Example Journal",
      doi: "10.1000/example",
      url: "https://example.com/paper",
      bibtexKey: "lovelace2024",
      bibtex: "@article{lovelace2024}",
    };

    const text = mount(ReferenceCard, {
      props: { reference },
    }).text();

    expect(text).toContain(reference.title);
    expect(text).toContain(reference.authors.join(", "));
    expect(text).toContain(String(reference.year));
    expect(text).not.toContain(reference.venue);
    expect(text).not.toContain(reference.doi);
    expect(text).not.toContain(reference.url);
  });

  it("keeps the three-line structure when metadata is missing", () => {
    const reference: Reference = {
      id: "reference-2",
      title: "",
      authors: [],
      bibtexKey: "unknown",
      bibtex: "@misc{unknown}",
    };
    const wrapper = mount(ReferenceCard, {
      props: { reference },
    });

    expect(wrapper.get("h3").text()).toBe("Untitled reference");
    expect(wrapper.get(".authors").text()).toBe("Unknown authors");
    expect(wrapper.get(".reference-card__year").text()).toBe("Unknown year");
  });
});
