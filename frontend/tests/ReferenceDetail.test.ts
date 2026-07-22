// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
];

const clipboardDescriptor = Object.getOwnPropertyDescriptor(
  Navigator.prototype,
  "clipboard",
);

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

afterEach(() => {
  vi.restoreAllMocks();
  if (clipboardDescriptor) {
    Object.defineProperty(Navigator.prototype, "clipboard", clipboardDescriptor);
  } else {
    Reflect.deleteProperty(Navigator.prototype, "clipboard");
  }
});

describe("ReferenceDetail BibTeX views", () => {
  it("shows and copies the highlighted stored source by default without loading export data", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue();
    Object.defineProperty(Navigator.prototype, "clipboard", {
      configurable: true,
      get: () => ({ writeText }),
    });
    const reference: Reference = {
      id: "demo",
      title: "A useful paper",
      authors: ["Ada Lovelace"],
      bibtexKey: "lovelace-demo",
      bibtex: "@article{lovelace-demo, title={A useful paper}}",
    };
    const wrapper = mount(ReferenceDetail, {
      props: { reference },
    });

    expect(wrapper.get('#bibtex-tab-stored').attributes("aria-selected")).toBe(
      "true",
    );
    expect(wrapper.get('#bibtex-tab-export').attributes("aria-selected")).toBe(
      "false",
    );
    expect(wrapper.findComponent(BibtexExportPanel).exists()).toBe(false);
    expect(apiMocks.listBibtexExportProfiles).not.toHaveBeenCalled();
    expect(apiMocks.exportBibtex).not.toHaveBeenCalled();

    const storedSource = wrapper.get('[data-testid="bibtex-stored-source"]');
    expect(storedSource.element.textContent).toBe(reference.bibtex);
    expect(storedSource.get(".bibtex-token--entry").text()).toBe("@article");
    expect(storedSource.get(".bibtex-token--key").text()).toBe(
      "lovelace-demo",
    );
    expect(storedSource.get(".bibtex-token--field").text()).toBe("title");
    expect(storedSource.get(".bibtex-token--value").text()).toBe(
      "{A useful paper}",
    );

    await wrapper.get("button.copy-button").trigger("click");
    await flushPromises();

    expect(writeText).toHaveBeenCalledWith(reference.bibtex);
    expect(wrapper.get("button.copy-button").text()).toBe("Copied");
    expect(wrapper.get('[aria-live="polite"]').text()).toBe(
      "BibTeX copied to clipboard.",
    );

    wrapper.unmount();
  });

  it("loads the export panel on first activation and preserves it across tab switches", async () => {
    const reference = makeReference("first", "First paper");
    const wrapper = mount(ReferenceDetail, {
      props: { reference },
    });

    await wrapper.get("#bibtex-tab-export").trigger("click");
    await flushPromises();

    expect(wrapper.get('#bibtex-tab-export').attributes("aria-selected")).toBe(
      "true",
    );
    expect(panelDisplay(wrapper.get("#bibtex-panel-stored").element)).toBe("none");
    expect(panelDisplay(wrapper.get("#bibtex-panel-export").element)).toBe("");
    expect(wrapper.getComponent(BibtexExportPanel).props()).toMatchObject({
      source: reference.bibtex,
      citationKey: reference.bibtexKey,
    });
    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportBibtex).toHaveBeenCalledTimes(1);

    await wrapper.get("#bibtex-tab-stored").trigger("click");
    expect(panelDisplay(wrapper.get("#bibtex-panel-stored").element)).toBe("");
    expect(panelDisplay(wrapper.get("#bibtex-panel-export").element)).toBe("none");
    expect(wrapper.findComponent(BibtexExportPanel).exists()).toBe(true);

    await wrapper.get("#bibtex-tab-export").trigger("click");
    await flushPromises();
    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportBibtex).toHaveBeenCalledTimes(1);

    wrapper.unmount();
  });

  it("resets to a lazy stored view when the selected reference changes", async () => {
    const wrapper = mount(ReferenceDetail, {
      props: { reference: makeReference("first", "First paper") },
    });

    await wrapper.get("#bibtex-tab-export").trigger("click");
    await flushPromises();
    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);

    const second = makeReference("second", "Second paper");
    await wrapper.setProps({ reference: second });
    await flushPromises();

    expect(wrapper.get('#bibtex-tab-stored').attributes("aria-selected")).toBe(
      "true",
    );
    expect(panelDisplay(wrapper.get("#bibtex-panel-stored").element)).toBe("");
    expect(panelDisplay(wrapper.get("#bibtex-panel-export").element)).toBe("none");
    expect(wrapper.findComponent(BibtexExportPanel).exists()).toBe(false);
    expect(wrapper.get('[data-testid="bibtex-stored-source"]').text()).toContain(
      "Second paper",
    );
    expect(apiMocks.listBibtexExportProfiles).toHaveBeenCalledTimes(1);

    wrapper.unmount();
  });

  it("supports arrow, Home, and End navigation between tabs", async () => {
    const wrapper = mount(ReferenceDetail, {
      attachTo: document.body,
      props: { reference: makeReference("keyboard", "Keyboard paper") },
    });
    const storedTab = wrapper.get<HTMLButtonElement>("#bibtex-tab-stored");
    storedTab.element.focus();

    await storedTab.trigger("keydown", { key: "ArrowRight" });
    await flushPromises();
    expect(wrapper.get('#bibtex-tab-export').attributes("aria-selected")).toBe(
      "true",
    );
    expect(document.activeElement).toBe(
      wrapper.get<HTMLButtonElement>("#bibtex-tab-export").element,
    );

    await wrapper.get("#bibtex-tab-export").trigger("keydown", { key: "Home" });
    await flushPromises();
    expect(wrapper.get('#bibtex-tab-stored').attributes("aria-selected")).toBe(
      "true",
    );
    expect(document.activeElement).toBe(
      wrapper.get<HTMLButtonElement>("#bibtex-tab-stored").element,
    );

    await wrapper.get("#bibtex-tab-stored").trigger("keydown", { key: "End" });
    await flushPromises();
    expect(wrapper.get('#bibtex-tab-export').attributes("aria-selected")).toBe(
      "true",
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

function panelDisplay(element: Element) {
  return (element as HTMLElement).style.display;
}
