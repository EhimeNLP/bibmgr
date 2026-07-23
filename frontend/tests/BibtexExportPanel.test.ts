// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BibtexExportPanel from "../src/components/BibtexExportPanel.vue";
import type { BibtexExportResult } from "../src/types/bibtex";

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
    id: "classical-bst",
    display_name: "Classical BibTeX",
    description: "Output for classical bibliography styles.",
    validation_profile: "classical-bst",
    preprint_representation: "misc-howpublished",
  },
];

const clipboardDescriptor = Object.getOwnPropertyDescriptor(
  Navigator.prototype,
  "clipboard",
);
const execCommandDescriptor = Object.getOwnPropertyDescriptor(
  document,
  "execCommand",
);

beforeEach(() => {
  apiMocks.exportBibtex.mockReset();
  apiMocks.listBibtexExportProfiles.mockReset();
  apiMocks.listBibtexExportProfiles.mockResolvedValue({
    schema_version: "1",
    profiles,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (clipboardDescriptor) {
    Object.defineProperty(Navigator.prototype, "clipboard", clipboardDescriptor);
  } else {
    Reflect.deleteProperty(Navigator.prototype, "clipboard");
  }
  if (execCommandDescriptor) {
    Object.defineProperty(document, "execCommand", execCommandDescriptor);
  } else {
    Reflect.deleteProperty(document, "execCommand");
  }
});

describe("BibtexExportPanel", () => {
  it("syntax-highlights the generated source without changing its text", async () => {
    const generated = `% optimized export
@article{paper2026,
  title = {A {Nested} Title},
  year = 2026,
}`;
    apiMocks.exportBibtex.mockResolvedValue(
      exportResult("laboratory", generated),
    );
    const wrapper = mount(BibtexExportPanel, {
      props: { source: "@article{paper2026, title={Raw}}" },
    });

    await flushPromises();

    const preview = wrapper.get('[data-testid="bibtex-export-preview"]');
    expect(preview.element.textContent).toBe(generated);
    expect(preview.get(".bibtex-token--comment").text()).toBe(
      "% optimized export",
    );
    expect(preview.get(".bibtex-token--entry").text()).toBe("@article");
    expect(preview.get(".bibtex-token--key").text()).toBe("paper2026");
    expect(
      preview.findAll(".bibtex-token--field").map((token) => token.text()),
    ).toEqual(["title", "year"]);
    expect(preview.get(".bibtex-token--value").text()).toBe(
      "{A {Nested} Title}",
    );
    expect(preview.get(".bibtex-token--number").text()).toBe("2026");

    wrapper.unmount();
  });

  it("uses the laboratory profile by default and regenerates the preview on selection", async () => {
    const source = "@misc{paper, title = {Paper}, eprint = {1706.03762}}";
    apiMocks.exportBibtex.mockImplementation(
      ({ profile }: { profile: string }) =>
        Promise.resolve(
          exportResult(
            profile,
            profile === "classical-bst"
              ? "@misc{paper, howpublished = {arXiv:1706.03762}}\n"
              : "@misc{paper, eprint = {1706.03762}}\n",
            profile === "laboratory"
              ? [{ record_index: 0, message: "Only the first URL was exported." }]
              : [],
          ),
        ),
    );
    const wrapper = mount(BibtexExportPanel, {
      props: { source, citationKey: "paper" },
    });

    await flushPromises();

    expect(wrapper.get("select").element.value).toBe("laboratory");
    expect(apiMocks.exportBibtex).toHaveBeenNthCalledWith(
      1,
      { source, profile: "laboratory" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toContain(
      "eprint",
    );
    expect(wrapper.get('[aria-label="Export warnings"]').text()).toContain(
      "Entry 1: Only the first URL was exported.",
    );

    await wrapper.get("select").setValue("classical-bst");
    await flushPromises();

    expect(apiMocks.exportBibtex).toHaveBeenNthCalledWith(
      2,
      { source, profile: "classical-bst" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toContain(
      "howpublished",
    );
    expect(wrapper.props("source")).toBe(source);

    wrapper.unmount();
  });

  it("ignores a stale export response after the profile changes", async () => {
    const laboratory = deferred<BibtexExportResult>();
    const classical = deferred<BibtexExportResult>();
    apiMocks.exportBibtex
      .mockReturnValueOnce(laboratory.promise)
      .mockReturnValueOnce(classical.promise);
    const wrapper = mount(BibtexExportPanel, {
      props: { source: "@misc{paper, title = {Paper}}" },
    });

    await flushPromises();
    const firstSignal = apiMocks.exportBibtex.mock.calls[0]?.[1]?.signal as AbortSignal;
    expect(wrapper.text()).toContain("Optimizing BibTeX");

    await wrapper.get("select").setValue("classical-bst");
    expect(firstSignal.aborted).toBe(true);
    classical.resolve(exportResult("classical-bst", "CLASSICAL OUTPUT"));
    await flushPromises();
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      "CLASSICAL OUTPUT",
    );

    laboratory.resolve(exportResult("laboratory", "STALE OUTPUT"));
    await flushPromises();
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      "CLASSICAL OUTPUT",
    );

    wrapper.unmount();
  });

  it("ignores a stale export response after the reference source changes", async () => {
    const firstReference = deferred<BibtexExportResult>();
    const secondReference = deferred<BibtexExportResult>();
    apiMocks.exportBibtex
      .mockReturnValueOnce(firstReference.promise)
      .mockReturnValueOnce(secondReference.promise);
    const wrapper = mount(BibtexExportPanel, {
      props: { source: "@misc{first, title = {First}}" },
    });

    await flushPromises();
    const firstSignal = apiMocks.exportBibtex.mock.calls[0]?.[1]?.signal as AbortSignal;
    await wrapper.setProps({ source: "@misc{second, title = {Second}}" });
    expect(firstSignal.aborted).toBe(true);

    secondReference.resolve(exportResult("laboratory", "SECOND OUTPUT"));
    await flushPromises();
    firstReference.resolve(exportResult("laboratory", "STALE FIRST OUTPUT"));
    await flushPromises();

    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toBe(
      "SECOND OUTPUT",
    );

    wrapper.unmount();
  });

  it("copies and downloads only the generated result", async () => {
    const generated = "@article{paper,\n  title = {Optimized},\n}\n";
    apiMocks.exportBibtex.mockResolvedValue(
      exportResult("laboratory", generated),
    );
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue();
    Object.defineProperty(Navigator.prototype, "clipboard", {
      configurable: true,
      get: () => ({ writeText }),
    });
    const createObjectURL = vi.fn().mockReturnValue("blob:bibtex-export");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    let downloadedAs = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      downloadedAs = this.download;
    });
    const wrapper = mount(BibtexExportPanel, {
      props: {
        source: "@article{paper, title={Raw}}",
        citationKey: "paper/key",
      },
    });

    await flushPromises();
    await wrapper.get("button.bibtex-export__copy").trigger("click");
    await flushPromises();

    expect(writeText).toHaveBeenCalledWith(generated);
    expect(wrapper.get("button.bibtex-export__copy").text()).toBe("Copied");

    await wrapper.get("button.bibtex-export__download").trigger("click");
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:bibtex-export");
    expect(downloadedAs).toBe("paper-key-laboratory.bib");

    wrapper.unmount();
  });

  it("restores keyboard focus after using the clipboard fallback", async () => {
    const generated = "@article{paper, title = {Optimized}}\n";
    apiMocks.exportBibtex.mockResolvedValue(
      exportResult("laboratory", generated),
    );
    const writeText = vi.fn().mockRejectedValue(new Error("Permission denied."));
    Object.defineProperty(Navigator.prototype, "clipboard", {
      configurable: true,
      get: () => ({ writeText }),
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });
    const wrapper = mount(BibtexExportPanel, {
      attachTo: document.body,
      props: { source: "@article{paper, title={Raw}}" },
    });

    await flushPromises();
    const copyButton = wrapper.get<HTMLButtonElement>("button.bibtex-export__copy");
    copyButton.element.focus();
    await copyButton.trigger("click");
    await flushPromises();

    expect(writeText).toHaveBeenCalledWith(generated);
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.activeElement).toBe(copyButton.element);

    wrapper.unmount();
  });

  it("shows export errors and lets the user retry", async () => {
    apiMocks.exportBibtex.mockRejectedValueOnce(new Error("Export is blocked."));
    const wrapper = mount(BibtexExportPanel, {
      props: { source: "@misc{paper}" },
    });

    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("Export is blocked.");
    apiMocks.exportBibtex.mockResolvedValueOnce(
      exportResult("laboratory", "@misc{paper,}\n"),
    );
    await wrapper.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="bibtex-export-preview"]').text()).toContain(
      "@misc{paper,}",
    );

    wrapper.unmount();
  });
});

function exportResult(
  profile: string,
  source: string,
  warnings: BibtexExportResult["warnings"] = [],
): BibtexExportResult {
  return {
    schema_version: "1",
    source,
    profile,
    record_count: 1,
    warnings,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}
