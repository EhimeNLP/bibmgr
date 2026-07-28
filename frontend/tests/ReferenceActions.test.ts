// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReferenceActions from "../src/components/ReferenceActions.vue";
import type { Reference } from "../src/types/reference";

const referenceApiMocks = vi.hoisted(() => ({
  deleteReference: vi.fn(),
  getReference: vi.fn(),
  updateReference: vi.fn(),
}));

const bibtexApiMocks = vi.hoisted(() => ({
  analyzeBibtex: vi.fn(),
  applyBibtexFixes: vi.fn(),
  exportBibtex: vi.fn(),
  listBibtexExportProfiles: vi.fn(),
}));

vi.mock("../src/api/references", () => referenceApiMocks);
vi.mock("../src/api/bibtex", () => bibtexApiMocks);

const storedSource =
  "@article{demo,\n  author = {Lovelace, Ada},\n  title = {Stored},\n  journal = {Journal},\n  year = {2026},\n}\n";
const sourceRevision = `sha256:${"1".repeat(64)}`;
const latestRevision = `sha256:${"2".repeat(64)}`;
const reference: Reference = {
  id: "demo-reference",
  title: "Stored",
  authors: ["Ada Lovelace"],
  bibtexKey: "demo",
  bibtex: storedSource,
  sourceRevision,
};
const exportProfiles = [
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

const wrappers: Array<ReturnType<typeof mount>> = [];

function renderActions(authenticated = true) {
  const wrapper = mount(ReferenceActions, {
    props: { reference, authenticated },
    attachTo: document.body,
    global: { stubs: { Teleport: true } },
  });
  wrappers.push(wrapper);
  return wrapper;
}

async function openActionsMenu(wrapper: ReturnType<typeof mount>) {
  await wrapper.get("button.reference-actions-trigger").trigger("click");
}

beforeEach(() => {
  referenceApiMocks.getReference.mockResolvedValue({
    ...reference,
    sourceRevision: latestRevision,
  });
  referenceApiMocks.updateReference.mockReset();
  referenceApiMocks.deleteReference.mockReset();
  bibtexApiMocks.analyzeBibtex.mockResolvedValue({
    schema_version: "1",
    source_revision: latestRevision,
    syntax: { entry_count: 1 },
    bibliography: { records: [], diagnostics: [] },
    diagnostics: [],
    available_fixes: [],
  });
  bibtexApiMocks.listBibtexExportProfiles.mockResolvedValue({
    schema_version: "1",
    profiles: exportProfiles,
  });
  bibtexApiMocks.exportBibtex.mockImplementation(
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
  for (const wrapper of wrappers.splice(0)) wrapper.unmount();
  document.body.classList.remove("reference-write-open");
  vi.clearAllMocks();
});

describe("ReferenceActions", () => {
  it("opens a compact menu and supports keyboard navigation", async () => {
    const wrapper = renderActions();
    const trigger = wrapper.get<HTMLButtonElement>(
      "button.reference-actions-trigger",
    );

    await trigger.trigger("keydown", { key: "ArrowDown" });
    await flushPromises();

    const editItem = wrapper.get<HTMLButtonElement>(
      "button.reference-action-edit",
    );
    const deleteItem = wrapper.get<HTMLButtonElement>(
      "button.reference-action-delete",
    );
    expect(wrapper.get('[role="menu"]').text()).toContain("Edit…");
    expect(wrapper.get('[role="menu"]').text()).toContain("Delete…");
    expect(document.activeElement).toBe(editItem.element);

    await editItem.trigger("keydown", { key: "ArrowDown" });
    expect(document.activeElement).toBe(deleteItem.element);

    await deleteItem.trigger("keydown", { key: "Escape" });
    await flushPromises();
    expect(wrapper.find('[role="menu"]').exists()).toBe(false);
    expect(document.activeElement).toBe(trigger.element);
  });

  it("routes unauthenticated edit and delete attempts to login", async () => {
    const wrapper = renderActions(false);

    await openActionsMenu(wrapper);
    await wrapper.get("button.reference-action-edit").trigger("click");
    await openActionsMenu(wrapper);
    await wrapper.get("button.reference-action-delete").trigger("click");

    expect(wrapper.emitted("loginRequired")).toHaveLength(2);
    expect(referenceApiMocks.getReference).not.toHaveBeenCalled();
    expect(referenceApiMocks.deleteReference).not.toHaveBeenCalled();
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false);
  });

  it("updates with the exact edited source and latest revision", async () => {
    const submitted = storedSource.replace("Stored", "Edited");
    const updated: Reference = {
      ...reference,
      title: "Edited",
      bibtex: submitted,
      sourceRevision: `sha256:${"3".repeat(64)}`,
    };
    referenceApiMocks.updateReference.mockResolvedValueOnce(updated);
    const wrapper = renderActions();

    await openActionsMenu(wrapper);
    await wrapper.get("button.reference-action-edit").trigger("click");
    await flushPromises();

    expect(referenceApiMocks.getReference).toHaveBeenCalledWith(reference.id);
    expect(
      wrapper.get<HTMLTextAreaElement>("#reference-edit-bibtex").element.value,
    ).toBe(storedSource);
    expect(bibtexApiMocks.exportBibtex).toHaveBeenCalledWith(
      { source: storedSource, profile: "laboratory" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(
      wrapper.get('[data-testid="bibtex-export-preview"]').text(),
    ).toBe(`${storedSource}\n% laboratory`);

    await wrapper
      .get<HTMLTextAreaElement>("#reference-edit-bibtex")
      .setValue(submitted);
    await flushPromises();

    expect(bibtexApiMocks.exportBibtex).toHaveBeenLastCalledWith(
      { source: submitted, profile: "laboratory" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    await wrapper
      .get(".reference-edit-actions button.button-primary")
      .trigger("click");
    await flushPromises();

    expect(referenceApiMocks.updateReference).toHaveBeenCalledWith(
      reference.id,
      {
        bibtex: submitted,
        source_revision: latestRevision,
      },
    );
    expect(wrapper.emitted("updated")).toEqual([[updated]]);
    expect(wrapper.find(".reference-edit-sheet").exists()).toBe(false);
    expect(bibtexApiMocks.analyzeBibtex).not.toHaveBeenCalled();
  });

  it("deletes only after confirmation and emits the deleted ID", async () => {
    referenceApiMocks.deleteReference.mockResolvedValueOnce(undefined);
    const wrapper = renderActions();

    await openActionsMenu(wrapper);
    await wrapper.get("button.reference-action-delete").trigger("click");

    expect(referenceApiMocks.deleteReference).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alertdialog"]').text()).toContain(
      "Delete Reference?",
    );
    expect(wrapper.get('[role="alertdialog"]').text()).toContain(
      "restore it later from History",
    );

    await wrapper
      .get(".confirmation-actions button.button-danger")
      .trigger("click");
    await flushPromises();

    expect(referenceApiMocks.deleteReference).toHaveBeenCalledWith(
      reference.id,
      reference.sourceRevision,
    );
    expect(wrapper.emitted("deleted")).toEqual([[reference.id]]);
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false);
  });

  it("cancels deletion without calling the API", async () => {
    const wrapper = renderActions();

    await openActionsMenu(wrapper);
    await wrapper.get("button.reference-action-delete").trigger("click");
    await wrapper
      .get(".confirmation-actions button.button-secondary")
      .trigger("click");
    await flushPromises();

    expect(referenceApiMocks.deleteReference).not.toHaveBeenCalled();
    expect(wrapper.emitted("deleted")).toBeUndefined();
  });
});
