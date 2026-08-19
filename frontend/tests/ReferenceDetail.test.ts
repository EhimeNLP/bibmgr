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
    id: "acl",
    display_name: "ACL Publications",
    description: "ACL-compatible BibTeX.",
    validation_profile: "acl",
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
        venue_name_style: "full",
        record_count: 1,
        warnings: [],
      }),
  );
});

describe("ReferenceDetail BibTeX views", () => {
  it("exports the stored source with the modern profile by default", async () => {
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
    await flushPromises();

    expect(wrapper.get(".bibtex-detail h3").text()).toBe("BibTeX");
    expect(wrapper.getComponent(BibtexExportPanel).props()).toMatchObject({
      source: reference.bibtex,
      citationKey: reference.bibtexKey,
    });
    const modernSource = wrapper.get('[data-testid="bibtex-export-preview"]');
    expect(modernSource.element.textContent).toBe(
      `${reference.bibtex}\n% modern`,
    );
    expect(modernSource.get(".bibtex-token--entry").text()).toBe("@article");
    expect(modernSource.get(".bibtex-token--key").text()).toBe(
      "lovelace-demo",
    );
    expect(modernSource.get(".bibtex-token--field").text()).toBe("title");
    expect(modernSource.get(".bibtex-token--value").text()).toBe(
      "{A useful paper}",
    );

    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportBibtex).toHaveBeenCalledWith(
      {
        source: reference.bibtex,
        profile: "modern",
        venue_name_style: "full",
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get("select").element.value).toBe("modern");
    expect(
      wrapper.findAll("option").map((option) => option.attributes("value")),
    ).toEqual(["acl", "modern"]);

    wrapper.unmount();
  });

  it("renders every selected profile into the same preview", async () => {
    const reference = makeReference("first", "First paper");
    const wrapper = mount(ReferenceDetail, {
      props: { reference, authenticated: false },
    });
    await flushPromises();

    await wrapper.get("select").setValue("acl");
    await flushPromises();

    expect(apiMocks.exportBibtex).toHaveBeenCalledTimes(2);
    expect(apiMocks.exportBibtex).toHaveBeenLastCalledWith(
      {
        source: reference.bibtex,
        profile: "acl",
        venue_name_style: "full",
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      `${reference.bibtex}\n% acl`,
    );

    await wrapper.get("select").setValue("modern");
    await flushPromises();

    expect(apiMocks.exportBibtex).toHaveBeenCalledTimes(3);
    expect(apiMocks.exportBibtex).toHaveBeenLastCalledWith(
      {
        source: reference.bibtex,
        profile: "modern",
        venue_name_style: "full",
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      `${reference.bibtex}\n% modern`,
    );
    wrapper.unmount();
  });

  it("re-exports the modern preview when the selected reference changes", async () => {
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
      `${second.bibtex}\n% modern`,
    );
    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportBibtex).toHaveBeenCalledTimes(2);
    expect(apiMocks.exportBibtex).toHaveBeenLastCalledWith(
      {
        source: second.bibtex,
        profile: "modern",
        venue_name_style: "full",
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

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
