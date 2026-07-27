// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BibtexExportPanel from "../src/components/BibtexExportPanel.vue";
import ReferenceDetail from "../src/components/ReferenceDetail.vue";
import type { Reference } from "../src/types/reference";

const apiMocks = vi.hoisted(() => ({
  exportBibtex: vi.fn(),
  listBibtexExportProfiles: vi.fn(),
}));

vi.mock("../src/api/bibtex", () => apiMocks);

const profiles = [
  {
    id: "laboratory",
    display_name: "Laboratory",
    description: "Laboratory-standard optimized BibTeX.",
    validation_profile: "laboratory",
    preprint_representation: "misc-eprint",
  },
  {
    id: "modern",
    display_name: "Modern",
    description: "General-purpose modern BibTeX.",
    validation_profile: "modern",
    preprint_representation: "misc-eprint",
  },
];

beforeEach(() => {
  apiMocks.exportBibtex.mockReset();
  apiMocks.listBibtexExportProfiles.mockReset();
  apiMocks.listBibtexExportProfiles.mockResolvedValue({
    schema_version: "1",
    profiles,
  });
  apiMocks.exportBibtex.mockImplementation(
    ({ source, profile }: { source: string; profile: string }) =>
      Promise.resolve({
        schema_version: "1",
        source: `${source}\n% ${profile}`,
        profile,
        record_count: 1,
        warnings: [],
      }),
  );
});

describe("ReferenceDetail BibTeX views", () => {
  it("shows the canonical laboratory source in the single preview by default", async () => {
    const reference: Reference = {
      id: "demo",
      title: "A useful paper",
      authors: ["Ada Lovelace"],
      bibtexKey: "lovelace-demo",
      bibtex: "@article{lovelace-demo, title={A useful paper}}",
    };
    const wrapper = mount(ReferenceDetail, {
      props: { reference, authenticated: false },
    });

    expect(wrapper.get(".bibtex-detail h3").text()).toBe("BibTeX");
    expect(wrapper.getComponent(BibtexExportPanel).props()).toMatchObject({
      source: reference.bibtex,
      citationKey: reference.bibtexKey,
      canonicalProfile: "laboratory",
    });
    const laboratorySource = wrapper.get('[data-testid="bibtex-export-preview"]');
    expect(laboratorySource.element.textContent).toBe(reference.bibtex);
    expect(laboratorySource.get(".bibtex-token--entry").text()).toBe("@article");
    expect(laboratorySource.get(".bibtex-token--key").text()).toBe(
      "lovelace-demo",
    );
    expect(laboratorySource.get(".bibtex-token--field").text()).toBe("title");
    expect(laboratorySource.get(".bibtex-token--value").text()).toBe(
      "{A useful paper}",
    );

    await flushPromises();

    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportBibtex).not.toHaveBeenCalled();
    expect(wrapper.get("select").element.value).toBe("laboratory");
    expect(
      wrapper.findAll("option").map((option) => option.attributes("value")),
    ).toEqual(["laboratory", "modern"]);

    wrapper.unmount();
  });

  it("renders another profile into the same preview and restores canonical source locally", async () => {
    const reference = makeReference("first", "First paper");
    const wrapper = mount(ReferenceDetail, {
      props: { reference, authenticated: false },
    });
    await flushPromises();

    await wrapper.get("select").setValue("modern");
    await flushPromises();

    expect(apiMocks.exportBibtex).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportBibtex).toHaveBeenCalledWith(
      { source: reference.bibtex, profile: "modern" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      `${reference.bibtex}\n% modern`,
    );

    await wrapper.get("select").setValue("laboratory");
    await flushPromises();

    expect(apiMocks.exportBibtex).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      reference.bibtex,
    );
    wrapper.unmount();
  });

  it("updates the default canonical preview when the selected reference changes", async () => {
    const wrapper = mount(ReferenceDetail, {
      props: {
        reference: makeReference("first", "First paper"),
        authenticated: false,
      },
    });
    await flushPromises();

    const second = makeReference("second", "Second paper");
    await wrapper.setProps({ reference: second });
    await flushPromises();

    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      second.bibtex,
    );
    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportBibtex).not.toHaveBeenCalled();

    wrapper.unmount();
  });
});

function makeReference(id: string, title: string): Reference {
  return {
    id,
    title,
    authors: ["Ada Lovelace"],
    bibtexKey: `${id}-paper`,
    bibtex: `@article{${id}-paper, title={${title}}}`,
  };
}
