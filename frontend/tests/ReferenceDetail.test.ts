// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReferenceDetail from "../src/components/ReferenceDetail.vue";
import type { Reference } from "../src/types/reference";

const clipboardDescriptor = Object.getOwnPropertyDescriptor(
  Navigator.prototype,
  "clipboard",
);

afterEach(() => {
  vi.restoreAllMocks();
  if (clipboardDescriptor) {
    Object.defineProperty(Navigator.prototype, "clipboard", clipboardDescriptor);
  } else {
    Reflect.deleteProperty(Navigator.prototype, "clipboard");
  }
});

describe("ReferenceDetail copy feedback", () => {
  it("copies BibTeX and announces the successful state", async () => {
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

    await wrapper.get("button.copy-button").trigger("click");
    await flushPromises();

    expect(writeText).toHaveBeenCalledWith(reference.bibtex);
    expect(wrapper.get("button.copy-button").text()).toBe("Copied");
    expect(wrapper.get('[aria-live="polite"]').text()).toBe(
      "BibTeX copied to clipboard.",
    );

    wrapper.unmount();
  });
});
