// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AnalyzeBibtexRequest,
  ApplyBibtexFixesRequest,
  ApplyBibtexFixesResult,
  BibtexAnalysisResult,
  BibtexDiagnostic,
  RegistrationValidationResult,
  ValidateRegistrationRequest,
} from "../src/types/bibtex";
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

const bibtexApiMocks = vi.hoisted(() => ({
  analyzeBibtex: vi.fn<
    (request: AnalyzeBibtexRequest) => Promise<BibtexAnalysisResult>
  >(),
  applyBibtexFixes: vi.fn<
    (request: ApplyBibtexFixesRequest) => Promise<ApplyBibtexFixesResult>
  >(),
  validateBibtexForRegistration: vi.fn<
    (request: ValidateRegistrationRequest) => Promise<RegistrationValidationResult>
  >(),
}));

vi.mock("../src/api/registration", () => apiMocks);
vi.mock("../src/api/bibtex", () => bibtexApiMocks);

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

const sourceRevision = `sha256:${"0".repeat(64)}`;

function analysisResult(
  diagnostics: BibtexDiagnostic[] = [],
  availableFixes: BibtexAnalysisResult["available_fixes"] = [],
): BibtexAnalysisResult {
  return {
    schema_version: "1",
    source_revision: sourceRevision,
    syntax: { status: "ok", entries: 1 },
    bibliography: { records: [], diagnostics: [] },
    diagnostics,
    available_fixes: availableFixes,
  };
}

beforeEach(() => {
  bibtexApiMocks.analyzeBibtex.mockResolvedValue(analysisResult());
  bibtexApiMocks.applyBibtexFixes.mockImplementation(async (request) => ({
    schema_version: "1",
    source: request.source,
    source_revision: sourceRevision,
    applied_fix_ids: request.fix_ids,
    analysis: analysisResult(),
  }));
  bibtexApiMocks.validateBibtexForRegistration.mockImplementation(
    async (request) => ({
      schema_version: "1",
      accepted: true,
      source: request.source,
      source_revision: sourceRevision,
      diagnostics: [],
      bibliography: { records: [], diagnostics: [] },
      applied_fix_ids: [],
      unresolved_semantics: false,
    }),
  );
});

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

  it("shows shared lint diagnostics and applies a safe quick fix", async () => {
    const source = "@article{demo, Title={A useful paper}}";
    const fixedSource = "@article{demo, title={A useful paper}}";
    const diagnostic: BibtexDiagnostic = {
      id: "BIB-SYNTAX-002:0",
      code: "BIB-SYNTAX-002",
      severity: "hint",
      blocking: false,
      message: "field `Title` should be spelled `title`",
      primary_location: {
        source_id: "source:0",
        range: { start: 15, end: 20 },
      },
      related_locations: [],
      notes: [],
      fixes: ["BIB-SYNTAX-002:0"],
    };
    const fix = {
      id: "BIB-SYNTAX-002:0",
      title: "Rename field to `title`",
      applicability: "safe" as const,
      source_revision: sourceRevision,
      edits: [{ range: { start: 15, end: 20 }, replacement: "title" }],
    };
    bibtexApiMocks.analyzeBibtex.mockResolvedValueOnce(
      analysisResult([diagnostic], [fix]),
    );
    bibtexApiMocks.applyBibtexFixes.mockResolvedValueOnce({
      schema_version: "1",
      source: fixedSource,
      source_revision: sourceRevision,
      applied_fix_ids: [fix.id],
      analysis: analysisResult(),
    });
    const wrapper = renderPanel();
    await openRegistration(wrapper);
    await wrapper.get("#manual-bibtex").setValue(source);

    const checkButton = wrapper.get(
      "#registration-panel-manual .bibtex-lint__check",
    );
    expect(checkButton.attributes("disabled")).toBeUndefined();
    await checkButton.trigger("click");
    await flushPromises();

    expect(bibtexApiMocks.analyzeBibtex).toHaveBeenCalledWith(
      { source, profile: "laboratory", mode: "tolerant" },
      { signal: expect.any(AbortSignal) },
    );

    const lint = wrapper.get("#registration-panel-manual .bibtex-lint");
    await vi.waitFor(() => {
      expect(lint.text()).toContain("BIB-SYNTAX-002");
    });
    expect(lint.text()).toContain("none are blocking");
    expect(lint.text()).toContain("Rename field to `title`");
    expect(
      wrapper.get("#registration-panel-manual .bibtex-diagnostic-range").text(),
    ).toBe("Title");

    await lint.get(".bibtex-fixes button").trigger("click");
    await flushPromises();

    expect(bibtexApiMocks.applyBibtexFixes).toHaveBeenCalledWith({
      source,
      source_revision: sourceRevision,
      fix_ids: [fix.id],
      profile: "laboratory",
    });
    await vi.waitFor(() => {
      expect(wrapper.get<HTMLTextAreaElement>("#manual-bibtex").element.value).toBe(
        fixedSource,
      );
    });
    await wrapper
      .get("#registration-panel-manual .bibtex-lint__check")
      .trigger("click");
    await flushPromises();
    expect(wrapper.get("#registration-panel-manual .bibtex-lint").text()).toContain(
      "No diagnostics",
    );
  });

  it("connects file lint diagnostics to the file editor", async () => {
    const source = "@article{demo, Title={From a file}}";
    const diagnostic: BibtexDiagnostic = {
      id: "BIB-SYNTAX-002:file",
      code: "BIB-SYNTAX-002",
      severity: "warning",
      blocking: false,
      message: "field `Title` should be spelled `title`",
      primary_location: {
        source_id: "source:0",
        range: { start: 15, end: 20 },
      },
      related_locations: [],
      notes: [],
      fixes: [],
    };
    bibtexApiMocks.analyzeBibtex.mockResolvedValueOnce(
      analysisResult([diagnostic]),
    );
    const wrapper = renderPanel();
    await openFilePanel(wrapper);
    await chooseFile(wrapper, createFile("diagnostic.bib", source));

    await wrapper
      .get("#registration-panel-file .bibtex-lint__check")
      .trigger("click");
    await flushPromises();

    expect(
      wrapper.get("#registration-panel-file .bibtex-diagnostic-range").text(),
    ).toBe("Title");
  });

  it("uses the native registration decision and preserves blocked input", async () => {
    const source = "@article{demo, title={Missing required data}}";
    const diagnostic: BibtexDiagnostic = {
      id: "LAB-ENTRY-003:0",
      code: "LAB-ENTRY-003",
      severity: "error",
      blocking: true,
      message: "required field `author` is missing",
      primary_location: null,
      related_locations: [],
      notes: [],
      fixes: [],
    };
    bibtexApiMocks.validateBibtexForRegistration.mockResolvedValueOnce({
      schema_version: "1",
      accepted: false,
      source,
      source_revision: sourceRevision,
      diagnostics: [diagnostic],
      bibliography: { records: [], diagnostics: [] },
      applied_fix_ids: [],
      unresolved_semantics: false,
    });
    bibtexApiMocks.analyzeBibtex.mockResolvedValueOnce(analysisResult([diagnostic]));
    const wrapper = renderPanel();
    await openRegistration(wrapper);
    await wrapper.get("#manual-bibtex").setValue(source);

    await wrapper
      .get("#registration-panel-manual button.button-primary")
      .trigger("click");
    await flushPromises();

    expect(apiMocks.registerBibtexToDatabase).not.toHaveBeenCalled();
    expect(wrapper.get('#registration-panel-manual [role="alert"]').text()).toContain(
      "Registration is blocked by 1 diagnostic",
    );
    expect(wrapper.get<HTMLTextAreaElement>("#manual-bibtex").element.value).toBe(
      source,
    );
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

  it("sends a braced raw percent value unchanged to native validation", async () => {
    const bibtex = "@misc{key, title = {100% Effective}, }";
    const percentOffset = bibtex.indexOf("%");
    bibtexApiMocks.validateBibtexForRegistration.mockResolvedValueOnce({
      schema_version: "1",
      accepted: false,
      source: bibtex,
      source_revision: sourceRevision,
      diagnostics: [
        {
          id: "BIB-SYNTAX-008:0",
          code: "BIB-SYNTAX-008",
          severity: "error",
          blocking: true,
          message: "field `title` contains an unescaped `%`",
          primary_location: {
            source_id: "source:0",
            range: { start: percentOffset, end: percentOffset + 1 },
          },
          related_locations: [],
          notes: [],
          fixes: ["BIB-SYNTAX-008:0"],
        },
      ],
      bibliography: { records: [], diagnostics: [] },
      applied_fix_ids: [],
      unresolved_semantics: false,
    });
    const wrapper = renderPanel();
    await openFilePanel(wrapper);

    await chooseFile(wrapper, createFile("percent.bib", bibtex));

    expect(wrapper.get('#registration-panel-file [role="status"]').text()).toBe(
      "percent.bib is ready. 1 entry detected.",
    );
    await wrapper
      .get("#registration-panel-file button.button-primary")
      .trigger("click");
    await flushPromises();

    expect(bibtexApiMocks.validateBibtexForRegistration).toHaveBeenCalledWith({
      source: bibtex,
      policy: "laboratory",
    });
    expect(apiMocks.registerBibtexToDatabase).not.toHaveBeenCalled();
  });

  it("uses native validation rather than the estimated entry count as authority", async () => {
    const source = "% metadata without a detected entry\n";
    bibtexApiMocks.validateBibtexForRegistration.mockResolvedValueOnce({
      schema_version: "1",
      accepted: false,
      source,
      source_revision: sourceRevision,
      diagnostics: [],
      bibliography: { records: [], diagnostics: [] },
      applied_fix_ids: [],
      unresolved_semantics: false,
    });
    const wrapper = renderPanel();
    await openFilePanel(wrapper);

    await chooseFile(wrapper, createFile("metadata.bib", source));

    expect(wrapper.get('#registration-panel-file [role="status"]').text()).toBe(
      "metadata.bib is ready. 0 entries detected.",
    );
    expect(wrapper.get("#file-bibtex-preview").exists()).toBe(true);
    const registerButton = wrapper.get(
      "#registration-panel-file button.button-primary",
    );
    expect(registerButton.attributes("disabled")).toBeUndefined();

    await registerButton.trigger("click");
    await flushPromises();

    expect(bibtexApiMocks.validateBibtexForRegistration).toHaveBeenCalledWith({
      source,
      policy: "laboratory",
    });
    expect(apiMocks.registerBibtexToDatabase).not.toHaveBeenCalled();
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
