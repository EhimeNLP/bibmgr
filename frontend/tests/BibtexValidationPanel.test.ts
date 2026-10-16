// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BibtexValidationPanel from "../src/components/BibtexValidationPanel.vue";
import type {
  AnalyzeBibtexRequest,
  ApplyBibtexFixesRequest,
  ApplyBibtexFixesResult,
  BibtexAnalysisResult,
  BibtexDiagnostic,
  BibtexFix,
} from "../src/types/bibtex";

const bibtexApiMocks = vi.hoisted(() => ({
  analyzeBibtex: vi.fn<
    (request: AnalyzeBibtexRequest) => Promise<BibtexAnalysisResult>
  >(),
  applyBibtexFixes: vi.fn<
    (request: ApplyBibtexFixesRequest) => Promise<ApplyBibtexFixesResult>
  >(),
}));

vi.mock("../src/api/bibtex", () => bibtexApiMocks);

const sourceRevision = `sha256:${"0".repeat(64)}`;
const source = "@article{demo, Title={A useful paper}}";
const fixedSource = "@article{demo, title={A useful paper}}";
const userEditedSource = "@article{demo, Title={A user edit}}";

const fix: BibtexFix = {
  id: "BIB-SYNTAX-002:0",
  title: "Rename field to `title`",
  applicability: "safe",
  source_revision: sourceRevision,
  edits: [{ range: { start: 15, end: 20 }, replacement: "title" }],
};

function analysisResult(
  availableFixes: BibtexFix[] = [],
  diagnostics: BibtexDiagnostic[] = [],
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

async function renderCheckedPanel() {
  bibtexApiMocks.analyzeBibtex.mockResolvedValueOnce(analysisResult([fix]));
  const wrapper = mount(BibtexValidationPanel, { props: { source } });
  await wrapper.get(".bibtex-lint__check").trigger("click");
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  bibtexApiMocks.analyzeBibtex.mockReset();
  bibtexApiMocks.applyBibtexFixes.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("BibtexValidationPanel", () => {
  it("runs real-time lint once after the input debounce", async () => {
    vi.useFakeTimers();
    bibtexApiMocks.analyzeBibtex.mockResolvedValueOnce(analysisResult());
    const wrapper = mount(BibtexValidationPanel, {
      props: { source: "", debounceMs: 250 },
    });

    await wrapper.setProps({ source: "@article{first}" });
    await vi.advanceTimersByTimeAsync(125);
    await wrapper.setProps({ source });
    await vi.advanceTimersByTimeAsync(249);
    expect(bibtexApiMocks.analyzeBibtex).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();

    expect(bibtexApiMocks.analyzeBibtex).toHaveBeenCalledOnce();
    expect(bibtexApiMocks.analyzeBibtex.mock.calls[0]?.[0]).toEqual({
      source,
      profile: "archive",
      mode: "tolerant",
    });
    expect(
      bibtexApiMocks.analyzeBibtex.mock.calls[0]?.[1]?.signal,
    ).toBeInstanceOf(AbortSignal);
    expect(wrapper.text()).toContain("No diagnostics");

    wrapper.unmount();
  });

  it("aborts an old request and ignores its response after a newer edit", async () => {
    vi.useFakeTimers();
    const first = deferred<BibtexAnalysisResult>();
    const second = deferred<BibtexAnalysisResult>();
    const oldDiagnostic = diagnostic("OLD", "Old source diagnostic");
    const currentDiagnostic = diagnostic("CURRENT", "Current source diagnostic");
    bibtexApiMocks.analyzeBibtex
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const wrapper = mount(BibtexValidationPanel, {
      props: { source, debounceMs: 100 },
    });

    await vi.advanceTimersByTimeAsync(100);
    const firstSignal = bibtexApiMocks.analyzeBibtex.mock.calls[0]?.[1]?.signal;
    expect(firstSignal?.aborted).toBe(false);

    await wrapper.setProps({ source: userEditedSource });
    expect(firstSignal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(100);

    second.resolve(analysisResult([], [currentDiagnostic]));
    await flushPromises();
    expect(wrapper.text()).toContain("Current source diagnostic");

    first.resolve(analysisResult([], [oldDiagnostic]));
    await flushPromises();
    expect(wrapper.text()).toContain("Current source diagnostic");
    expect(wrapper.text()).not.toContain("Old source diagnostic");
    expect(wrapper.emitted("update:diagnostics")?.at(-1)).toEqual([
      [currentDiagnostic],
    ]);

    wrapper.unmount();
  });

  it("keeps manual checking and displays related locations and notes", async () => {
    const detailedDiagnostic: BibtexDiagnostic = {
      ...diagnostic("BIB-DUPLICATE-001", "field `title` is duplicated"),
      related_locations: [
        {
          message: "the first field is here",
          location: {
            source_id: "source:0",
            range: { start: 15, end: 20 },
          },
        },
      ],
      notes: ["The last field value takes precedence."],
    };
    bibtexApiMocks.analyzeBibtex.mockResolvedValueOnce(
      analysisResult([], [detailedDiagnostic]),
    );
    const wrapper = mount(BibtexValidationPanel, { props: { source } });

    await wrapper.get(".bibtex-lint__check").trigger("click");
    await flushPromises();

    expect(wrapper.get('[aria-label="Related locations"]').text()).toContain(
      "the first field is here",
    );
    expect(wrapper.get('[aria-label="Diagnostic notes"]').text()).toContain(
      "The last field value takes precedence.",
    );
    expect(bibtexApiMocks.analyzeBibtex).toHaveBeenCalledOnce();

    wrapper.unmount();
  });

  it("discards a fix response when the source changes while the fix request is pending", async () => {
    const pendingFix = deferred<ApplyBibtexFixesResult>();
    bibtexApiMocks.applyBibtexFixes.mockReturnValueOnce(pendingFix.promise);
    const wrapper = await renderCheckedPanel();

    await wrapper.get(".bibtex-fixes button").trigger("click");
    await wrapper.setProps({ source: userEditedSource });
    pendingFix.resolve({
      schema_version: "1",
      source: fixedSource,
      source_revision: sourceRevision,
      applied_fix_ids: [fix.id],
      analysis: analysisResult(),
    });
    await flushPromises();

    expect(wrapper.emitted("update:source")).toBeUndefined();
    expect(wrapper.emitted("fixed")).toBeUndefined();
    expect(bibtexApiMocks.analyzeBibtex).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("Source changed after the last check");

    wrapper.unmount();
  });

  it("discards fallback reanalysis when the source changes while it is pending", async () => {
    const pendingAnalysis = deferred<BibtexAnalysisResult>();
    bibtexApiMocks.applyBibtexFixes.mockResolvedValueOnce({
      schema_version: "1",
      source: fixedSource,
      source_revision: sourceRevision,
      applied_fix_ids: [fix.id],
    });
    const wrapper = await renderCheckedPanel();
    bibtexApiMocks.analyzeBibtex.mockReturnValueOnce(pendingAnalysis.promise);

    await wrapper.get(".bibtex-fixes button").trigger("click");
    await vi.waitFor(() => {
      expect(bibtexApiMocks.analyzeBibtex).toHaveBeenCalledTimes(2);
    });
    await wrapper.setProps({ source: userEditedSource });
    pendingAnalysis.resolve(analysisResult());
    await flushPromises();

    expect(wrapper.emitted("update:source")).toBeUndefined();
    expect(wrapper.emitted("fixed")).toBeUndefined();
    expect(wrapper.text()).toContain("Source changed after the last check");

    wrapper.unmount();
  });
});

function diagnostic(code: string, message: string): BibtexDiagnostic {
  return {
    id: `${code}:0`,
    code,
    severity: "warning",
    blocking: false,
    message,
    primary_location: {
      source_id: "source:0",
      range: { start: 0, end: 8 },
    },
    related_locations: [],
    notes: [],
    fixes: [],
  };
}

it("hides automatically covered information and safe controls, but retains all actionable diagnostics", async () => {
  const info = Array.from({ length: 8 }, (_, index) => ({
    ...diagnostic(`INFO-${index}`, `Automatic information ${index}`),
    severity: index % 2 ? "hint" as const : "information" as const,
    fixes: [fix.id],
  }));
  const warning = { ...diagnostic("WARN", "Visible warning"), fixes: [fix.id] };
  const error = { ...diagnostic("ERROR", "Visible error"), severity: "error" as const, fixes: [fix.id] };
  const blocking = { ...diagnostic("BLOCK", "Visible blocking information"), severity: "information" as const, blocking: true, fixes: [fix.id] };
  const manual = { ...diagnostic("MANUAL", "Review this suggestion"), severity: "information" as const, fixes: ["review"] };
  const mixed = { ...manual, id: "mixed", message: "Mixed safe and manual fixes", fixes: [fix.id, "review"] };
  const unknown = { ...manual, id: "unknown", message: "Unknown fix must stay visible", fixes: ["missing"] };
  const noFix = { ...manual, id: "no-fix", message: "Information without a fix", fixes: [] };
  const remaining = [warning, error, blocking, manual, mixed, unknown, noFix];
  bibtexApiMocks.analyzeBibtex.mockResolvedValue(analysisResult([
    fix,
    { ...fix, id: "review", title: "Review suggestion", applicability: "requires_confirmation" },
    { ...fix, id: "unsafe", title: "Manual correction", applicability: "unsafe" },
  ], [...info, ...remaining]));
  const wrapper = mount(BibtexValidationPanel, { props: { source, safeFixesOnExport: true } });
  await wrapper.get(".bibtex-lint__check").trigger("click");
  await flushPromises();
  expect(wrapper.find("details").exists()).toBe(false);
  expect(wrapper.findAll(".bibtex-diagnostic")).toHaveLength(remaining.length);
  expect(wrapper.text()).not.toContain("Automatic information");
  expect(wrapper.text()).not.toContain(fix.title);
  for (const item of remaining) expect(wrapper.text()).toContain(item.message);
  expect(wrapper.get(".bibtex-lint__summary").text()).toBe("7 diagnostics; 1 is blocking.");
  expect(wrapper.findAll(".bibtex-lint__automatic-fixes")).toHaveLength(1);
  expect(wrapper.findAll(".bibtex-fixes button").map(button => button.text())).toEqual(["Review and apply", "Manual fix only"]);
  expect(wrapper.emitted("update:diagnostics")?.at(-1)).toEqual([remaining]);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  bibtexApiMocks.applyBibtexFixes.mockResolvedValue({ schema_version: "1", source: fixedSource, source_revision: sourceRevision, applied_fix_ids: ["review"], analysis: analysisResult() });
  await wrapper.get(".bibtex-fixes button").trigger("click");
  await flushPromises();
  expect(confirm).toHaveBeenCalledOnce();
  expect(wrapper.emitted("update:source")?.at(-1)).toEqual([fixedSource]);
  wrapper.unmount();
});

it("does not claim the input has no diagnostics when all diagnostics are automatically handled", async () => {
  bibtexApiMocks.analyzeBibtex.mockResolvedValue(analysisResult([fix], [{
    ...diagnostic("AUTO", "Handled on export"), severity: "information", fixes: [fix.id],
  }]));
  const wrapper = mount(BibtexValidationPanel, { props: { source, safeFixesOnExport: true } });
  await wrapper.get(".bibtex-lint__check").trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("No diagnostics require manual attention.");
  expect(wrapper.text()).not.toContain("This source passes");
  expect(wrapper.find(".bibtex-diagnostic").exists()).toBe(false);
  expect(wrapper.find(".bibtex-fixes").exists()).toBe(false);
  expect(wrapper.emitted("update:diagnostics")?.at(-1)).toEqual([[]]);
  expect(bibtexApiMocks.applyBibtexFixes).not.toHaveBeenCalled();
  expect(wrapper.emitted("update:source")).toBeUndefined();
  wrapper.unmount();
});

it("keeps informational fixes available in editors without automatic export handling", async () => {
  bibtexApiMocks.analyzeBibtex.mockResolvedValue(analysisResult([fix], [{
    ...diagnostic("AUTO", "Available correction"), severity: "information", fixes: [fix.id],
  }]));
  const wrapper = mount(BibtexValidationPanel, { props: { source } });
  await wrapper.get(".bibtex-lint__check").trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("Available correction");
  expect(wrapper.get(".bibtex-fixes button").text()).toBe("Apply fix");
  expect(wrapper.find(".bibtex-lint__automatic-fixes").exists()).toBe(false);
  wrapper.unmount();
});
