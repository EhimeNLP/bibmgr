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
  canonicalizeBibtexForStorage: vi.fn(),
  validateBibtexForRegistration: vi.fn(),
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

function accepted(source: string) {
  return {
    schema_version: "1" as const,
    accepted: true,
    source,
    source_revision: latestRevision,
    diagnostics: [],
    bibliography: { records: [], diagnostics: [] },
    applied_fix_ids: [],
    unresolved_semantics: false,
  };
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
  bibtexApiMocks.validateBibtexForRegistration.mockImplementation(
    ({ source }: { source: string }) => Promise.resolve(accepted(source)),
  );
  bibtexApiMocks.canonicalizeBibtexForStorage.mockImplementation(
    ({ source }: { source: string }) => Promise.resolve(accepted(source)),
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

  it("validates, previews canonicalization, and updates with the latest revision", async () => {
    const submitted = storedSource.replace("Stored", "Edited");
    const canonical = submitted.replace("title = {Edited}", "title={Edited}");
    const updated: Reference = {
      ...reference,
      title: "Edited",
      bibtex: canonical,
      sourceRevision: `sha256:${"3".repeat(64)}`,
    };
    bibtexApiMocks.canonicalizeBibtexForStorage.mockResolvedValueOnce(
      accepted(canonical),
    );
    referenceApiMocks.updateReference.mockResolvedValueOnce(updated);
    const wrapper = renderActions();

    await openActionsMenu(wrapper);
    await wrapper.get("button.reference-action-edit").trigger("click");
    await flushPromises();

    expect(referenceApiMocks.getReference).toHaveBeenCalledWith(reference.id);
    expect(
      wrapper.get<HTMLTextAreaElement>("#reference-edit-bibtex").element.value,
    ).toBe(storedSource);

    await wrapper
      .get<HTMLTextAreaElement>("#reference-edit-bibtex")
      .setValue(submitted);
    await wrapper
      .get(".reference-edit-actions button.button-primary")
      .trigger("click");
    await flushPromises();

    expect(referenceApiMocks.updateReference).not.toHaveBeenCalled();
    expect(
      wrapper.get('[data-testid="edit-canonical-preview"]').element.textContent,
    ).toBe(canonical);
    expect(
      wrapper.get(".reference-edit-actions button.button-primary").text(),
    ).toBe("Save normalized changes");

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
