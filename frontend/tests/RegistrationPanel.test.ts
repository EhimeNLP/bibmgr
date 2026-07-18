// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  RegisterBibtexPayload,
  RegisterBibtexResult,
} from "../src/types/reference";
import RegistrationPanel from "../src/components/RegistrationPanel.vue";

const apiMocks = vi.hoisted(() => ({
  registerBibtexToDatabase: vi.fn<
    (payload: RegisterBibtexPayload) => Promise<RegisterBibtexResult>
  >(),
}));

vi.mock("../src/api/registration", () => apiMocks);

const wrappers: Array<ReturnType<typeof mount>> = [];

function renderPanel() {
  const wrapper = mount(RegistrationPanel, {
    attachTo: document.body,
    global: {
      stubs: { Teleport: true },
    },
  });
  wrappers.push(wrapper);
  return wrapper;
}

async function openRegistration(wrapper: ReturnType<typeof mount>) {
  const trigger = wrapper.get("button.registration-trigger");
  if (trigger.attributes("aria-expanded") !== "true") {
    await trigger.trigger("click");
  }
  return wrapper.get(".registration-sheet");
}

async function openFilePanel(wrapper: ReturnType<typeof mount>) {
  await openRegistration(wrapper);
  await wrapper.get("#registration-tab-file").trigger("click");
}

function createFile(name: string, contents: string, readError?: Error) {
  const file = new File([contents], name, { type: "text/x-bibtex" });
  Object.defineProperty(file, "text", {
    configurable: true,
    value: readError
      ? vi.fn().mockRejectedValue(readError)
      : vi.fn().mockResolvedValue(contents),
  });
  return file;
}

async function chooseFile(wrapper: ReturnType<typeof mount>, file: File) {
  const input = wrapper.get<HTMLInputElement>("#bibtex-file");
  Object.defineProperty(input.element, "files", {
    configurable: true,
    value: [file],
  });
  await input.trigger("change");
  await flushPromises();
}

afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount();
  wrappers.length = 0;
  vi.resetAllMocks();
});

describe("RegistrationPanel", () => {
  it("opens as a modal sheet and restores focus when dismissed", async () => {
    const wrapper = renderPanel();
    const trigger = wrapper.get("button.registration-trigger");
    trigger.element.focus();

    const sheet = await openRegistration(wrapper);
    expect(trigger.attributes("aria-expanded")).toBe("true");
    expect(sheet.attributes()).toMatchObject({
      role: "dialog",
      "aria-modal": "true",
    });

    await sheet.trigger("keydown", { key: "Escape" });
    await flushPromises();

    expect(wrapper.find(".registration-sheet").exists()).toBe(false);
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger.element);
  });

  it("switches between Manual entry and BibTeX file with roving tab focus", async () => {
    const wrapper = renderPanel();
    await openRegistration(wrapper);
    const manualTab = wrapper.get("#registration-tab-manual");

    expect(manualTab.attributes("aria-selected")).toBe("true");
    expect(wrapper.get("#registration-panel-manual").isVisible()).toBe(true);
    expect(wrapper.get("#registration-panel-file").isVisible()).toBe(false);

    await manualTab.trigger("keydown", { key: "ArrowRight" });

    const fileTab = wrapper.get("#registration-tab-file");
    expect(fileTab.attributes()).toMatchObject({
      "aria-selected": "true",
      "aria-controls": "registration-panel-file",
      tabindex: "0",
    });
    expect(document.activeElement).toBe(fileTab.element);
    expect(wrapper.get("#registration-panel-file").isVisible()).toBe(true);
    expect(wrapper.get("#registration-panel-manual").isVisible()).toBe(false);
    expect(wrapper.text()).not.toContain("PDF");
  });

  it("submits the exact manual BibTeX with busy and success feedback", async () => {
    let resolveRegistration!: (value: RegisterBibtexResult) => void;
    const registration = new Promise<RegisterBibtexResult>((resolve) => {
      resolveRegistration = resolve;
    });
    apiMocks.registerBibtexToDatabase.mockReturnValueOnce(registration);
    const wrapper = renderPanel();
    await openRegistration(wrapper);
    const bibtex = "@article{demo,\n  title = {A useful paper}\n}";

    await wrapper.get("#manual-bibtex").setValue(bibtex);
    await wrapper
      .get("#registration-panel-manual button.button-primary")
      .trigger("click");

    expect(apiMocks.registerBibtexToDatabase).toHaveBeenCalledWith({
      bibtex,
      source: "manual",
    });
    const registerButton = wrapper.get(
      "#registration-panel-manual button.button-primary",
    );
    expect(registerButton.attributes()).toMatchObject({
      "aria-busy": "true",
      disabled: "",
    });
    expect(registerButton.text()).toContain("Registering…");

    const reference = {
      id: "demo",
      title: "A useful paper",
      authors: [],
      bibtex,
    };
    resolveRegistration({ reference });
    await flushPromises();

    expect(
      wrapper.get('#registration-panel-manual [role="status"]').text(),
    ).toBe("Registered.");
    expect(wrapper.get<HTMLTextAreaElement>("#manual-bibtex").element.value).toBe(
      "",
    );
    expect(wrapper.emitted("registered")).toEqual([[reference]]);
  });

  it("surfaces manual registration failures and preserves the entry", async () => {
    apiMocks.registerBibtexToDatabase.mockRejectedValueOnce(
      new Error("Registration service unavailable."),
    );
    const wrapper = renderPanel();
    await openRegistration(wrapper);
    const bibtex = "@article{demo, title={A useful paper}}";

    await wrapper.get("#manual-bibtex").setValue(bibtex);
    await wrapper
      .get("#registration-panel-manual button.button-primary")
      .trigger("click");
    await flushPromises();

    expect(
      wrapper.get('#registration-panel-manual [role="alert"]').text(),
    ).toBe("Registration service unavailable.");
    expect(wrapper.get<HTMLTextAreaElement>("#manual-bibtex").element.value).toBe(
      bibtex,
    );
    expect(wrapper.emitted("registered")).toBeUndefined();
  });

  it("reads, previews, edits, and registers one .bib file", async () => {
    const originalBibtex = "@article{demo,\n  title = {From a file}\n}";
    const editedBibtex = originalBibtex.replace("From a file", "Reviewed title");
    const file = createFile("reference.BIB", originalBibtex);
    const reference = {
      id: "file-demo",
      title: "Reviewed title",
      authors: [],
      bibtex: editedBibtex,
    };
    apiMocks.registerBibtexToDatabase.mockResolvedValueOnce({ reference });
    const wrapper = renderPanel();
    await openFilePanel(wrapper);

    expect(wrapper.get("#bibtex-file").attributes("accept")).toContain(".bib");
    await chooseFile(wrapper, file);

    expect(wrapper.get('#registration-panel-file [role="status"]').text()).toBe(
      "reference.BIB is ready. 1 entry detected.",
    );
    const preview = wrapper.get<HTMLTextAreaElement>("#file-bibtex-preview");
    expect(preview.element.value).toBe(originalBibtex);
    await preview.setValue(editedBibtex);

    await wrapper
      .get("#registration-panel-file button.button-primary")
      .trigger("click");
    await flushPromises();

    expect(apiMocks.registerBibtexToDatabase).toHaveBeenCalledWith({
      bibtex: editedBibtex,
      source: "file",
    });
    expect(wrapper.get('#registration-panel-file [role="status"]').text()).toBe(
      "reference.BIB was registered.",
    );
    expect(wrapper.find("#file-bibtex-preview").exists()).toBe(false);
    expect(wrapper.emitted("registered")).toEqual([[reference]]);
  });

  it("accepts and preserves multiple entries from one .bib file", async () => {
    const bibtex = "@article{one, title={One}}\n\n@book{two, title={Two}}";
    const reference = {
      id: "library",
      title: "Imported library",
      authors: [],
      bibtex,
    };
    apiMocks.registerBibtexToDatabase.mockResolvedValueOnce({ reference });
    const wrapper = renderPanel();
    await openFilePanel(wrapper);

    await chooseFile(wrapper, createFile("library.bib", bibtex));

    expect(wrapper.get('#registration-panel-file [role="status"]').text()).toBe(
      "library.bib is ready. 2 entries detected.",
    );
    expect(
      wrapper.get<HTMLTextAreaElement>("#file-bibtex-preview").element.value,
    ).toBe(bibtex);
    const registerButton = wrapper.get(
      "#registration-panel-file button.button-primary",
    );
    expect(registerButton.text()).toBe("Register 2 references");

    await registerButton.trigger("click");
    await flushPromises();

    expect(apiMocks.registerBibtexToDatabase).toHaveBeenCalledWith({
      bibtex,
      source: "file",
    });
  });

  it("rejects invalid and empty files without stale content", async () => {
    const wrapper = renderPanel();
    await openFilePanel(wrapper);

    await chooseFile(
      wrapper,
      createFile("reference.txt", "@article{demo, title={Wrong extension}}"),
    );
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Choose a file with the .bib extension.",
    );

    await chooseFile(wrapper, createFile("empty.bib", "  \n"));
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "The selected .bib file is empty.",
    );

    expect(wrapper.find("#file-bibtex-preview").exists()).toBe(false);
    expect(
      wrapper
        .get("#registration-panel-file button.button-primary")
        .attributes("disabled"),
    ).toBe("");
    expect(apiMocks.registerBibtexToDatabase).not.toHaveBeenCalled();
  });

  it("reports local file read failures as an accessible error", async () => {
    const wrapper = renderPanel();
    await openFilePanel(wrapper);

    await chooseFile(
      wrapper,
      createFile("broken.bib", "ignored", new Error("Read failed")),
    );

    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Could not read broken.bib: Read failed",
    );
    expect(wrapper.find("#file-bibtex-preview").exists()).toBe(false);
    expect(apiMocks.registerBibtexToDatabase).not.toHaveBeenCalled();
  });
});
