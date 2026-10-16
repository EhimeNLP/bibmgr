// @vitest-environment jsdom
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import DuplicateOverwrite from "../src/components/DuplicateOverwrite.vue";
import UnifiedDiff from "../src/components/UnifiedDiff.vue";
import { DuplicateReviewError, type DuplicateFinding } from "../src/api/duplicates";

const api = vi.hoisted(() => ({ getReference: vi.fn(), updateReference: vi.fn() }));
vi.mock("../src/api/references", () => api);
const source = "@article{new,title={New}}";
const stored = { id: "existing", title: "Old", bibtex: "@article{old,title={Old}}", sourceRevision: `sha256:${"1".repeat(64)}` };
beforeEach(() => { vi.resetAllMocks(); api.getReference.mockResolvedValue(stored); });

it("shows a unified diff preserving aligned fields, blank lines, and value indentation while submitting the original source", async () => {
  const original = '@article{new,\n    title     = {A long title with {Protected} text},\n    author    = {Doe, Jane and\n                 Roe, Richard},\n\n\tjournal = {{Venue}},\n    year      = {2024},\n}\n';
  const previous = original.replace("{2024}", "{2023}");
  api.getReference.mockResolvedValue({ ...stored, bibtex: previous });
  api.updateReference.mockResolvedValue({ ...stored, bibtex: original });
  const wrapper = mount(DuplicateOverwrite, { props: { referenceId: stored.id, source: original } });
  await flushPromises();
  const diff = wrapper.getComponent(UnifiedDiff);
  expect(diff.props("before")).toBe(previous);
  expect(diff.props("after")).toBe(original);
  expect(diff.get("tr.is-deletion code").element.textContent).toBe("    year      = {2023},");
  expect(diff.get("tr.is-addition code").element.textContent).toBe("    year      = {2024},");
  const contextLines = diff.findAll("tr.is-context code").map(line => line.element.textContent);
  expect(contextLines).toContain("                 Roe, Richard},");
  expect(contextLines).toContain("\tjournal = {{Venue}},");
  expect(contextLines).toContain("\u00a0");
  await wrapper.get("button.button-primary").trigger("click");
  await flushPromises();
  expect(api.updateReference).toHaveBeenCalledWith(stored.id, { bibtex: original, source_revision: stored.sourceRevision });
  wrapper.unmount();
});

it("confirms new possible matches through update rather than creating a separate reference", async () => {
  const finding: DuplicateFinding = { incoming_index: 0, candidate_index: 0, existing: true, reference_id: "other",
    title: "Other paper", action: "confirm", comparison: { kind: "title", fields: [] } };
  api.updateReference.mockRejectedValueOnce(new DuplicateReviewError([finding], "a".repeat(64)))
    .mockResolvedValueOnce({ ...stored, title: "New", bibtex: source });
  const wrapper = mount(DuplicateOverwrite, { props: { referenceId: stored.id, source } });
  await flushPromises();
  await wrapper.get("button.button-primary").trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("Other paper");
  expect(wrapper.text()).not.toContain("Save as a separate reference");
  expect(wrapper.get("button.button-primary").attributes("disabled")).toBeDefined();
  await wrapper.get(".duplicate-review > button").trigger("click");
  await flushPromises();
  expect(api.updateReference).toHaveBeenLastCalledWith(stored.id, {
    bibtex: source, source_revision: stored.sourceRevision, duplicate_confirmation: "a".repeat(64),
  });
  expect(wrapper.emitted("saved")).toHaveLength(1);
  wrapper.unmount();
});

it("requires a new review after reloading a stale reference and drops old confirmation", async () => {
  api.updateReference.mockRejectedValueOnce(new Error("The reference has changed since it was loaded."));
  const wrapper = mount(DuplicateOverwrite, { props: { referenceId: stored.id, source } });
  await flushPromises();
  await wrapper.get("button.button-primary").trigger("click");
  await flushPromises();
  const fresh = { ...stored, title: "Edited by someone else", sourceRevision: `sha256:${"2".repeat(64)}` };
  api.getReference.mockResolvedValueOnce(fresh);
  await wrapper.findAll("button").find(button => button.text() === "Reload stored reference")!.trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain(fresh.title);
  expect(api.updateReference).toHaveBeenCalledTimes(1);
  api.updateReference.mockResolvedValueOnce({ ...fresh, bibtex: source });
  await wrapper.get("button.button-primary").trigger("click");
  await flushPromises();
  expect(api.updateReference).toHaveBeenLastCalledWith(stored.id, { bibtex: source, source_revision: fresh.sourceRevision });
  wrapper.unmount();
});

it("discards stale loads and does not allow saving without a revision", async () => {
  let resolve!: (value: unknown) => void;
  api.getReference.mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValueOnce({ title: "Missing revision" });
  const wrapper = mount(DuplicateOverwrite, { props: { referenceId: stored.id, source } });
  await wrapper.setProps({ referenceId: "other" });
  await flushPromises();
  resolve(stored);
  await flushPromises();
  expect(wrapper.get('[role="alert"]').text()).toContain("no revision");
  expect(wrapper.get("button.button-primary").attributes("disabled")).toBeDefined();
  expect(api.updateReference).not.toHaveBeenCalled();
  wrapper.unmount();
});
