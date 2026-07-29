// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import HistoryPanel from "../src/components/HistoryPanel.vue";

const historyApi = vi.hoisted(() => ({
  pageReferenceHistory: vi.fn(),
  getReferenceHistory: vi.fn(),
  revertReference: vi.fn(),
}));

vi.mock("../src/api/history", () => historyApi);

const referenceId = "4546d52e-39dc-4031-9df5-07c06f816a48";
const summary = {
  referenceId,
  headRevision: 2,
  exists: false,
  title: "Deleted paper",
  latestAction: "delete" as const,
  updatedAt: "2026-07-27T12:00:00Z",
};
const history = {
  referenceId,
  headRevision: 2,
  exists: false,
  revisions: [
    {
      revision: 2,
      action: "delete" as const,
      actor: {
        id: "7ca9f85d-b16f-470b-a6a8-ab6d8582eb36",
        email: "member@ai.cs.ehime-u.ac.jp",
      },
      occurredAt: "2026-07-27T12:00:00Z",
      title: "Deleted paper",
      restorable: false,
    },
    {
      revision: 1,
      action: "create" as const,
      actor: {
        id: "7ca9f85d-b16f-470b-a6a8-ab6d8582eb36",
        email: "member@ai.cs.ehime-u.ac.jp",
      },
      occurredAt: "2026-07-27T10:00:00Z",
      title: "Original paper",
      submittedBibtex: "@article{original,Title={Original paper}}",
      canonicalBibtex: (
        "@article{original,\n" +
        "  title = {Original paper},\n" +
        "}\n"
      ),
      restorable: true,
    },
  ],
};
const restored = {
  id: referenceId,
  title: "Original paper",
  authors: [],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.resetAllMocks();
  document.body.classList.remove("history-open");
});

describe("HistoryPanel", () => {
  it("requires login before showing history", async () => {
    const wrapper = mount(HistoryPanel, {
      props: { authenticated: false },
    });

    await wrapper.get("button.history-trigger").trigger("click");

    expect(wrapper.emitted("loginRequired")).toEqual([[]]);
    expect(wrapper.find(".history-sheet").exists()).toBe(false);
    wrapper.unmount();
  });

  it("restores a deleted revision after explicit confirmation", async () => {
    historyApi.pageReferenceHistory
      .mockResolvedValueOnce({
        items: [summary],
        total: 1,
        limit: 25,
        offset: 0,
      })
      .mockResolvedValueOnce({
        items: [
          {
            ...summary,
            headRevision: 3,
            exists: true,
            latestAction: "restore",
          },
        ],
        total: 1,
        limit: 25,
        offset: 0,
      });
    historyApi.getReferenceHistory
      .mockResolvedValueOnce(history)
      .mockResolvedValueOnce({
        ...history,
        headRevision: 3,
        exists: true,
      });
    historyApi.revertReference.mockResolvedValue(restored);
    const wrapper = mount(HistoryPanel, {
      props: { authenticated: true },
      attachTo: document.body,
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get("button.history-trigger").trigger("click");
    await flushPromises();
    const restoreButtons = wrapper.findAll("button.history-restore");
    expect(restoreButtons).toHaveLength(1);
    expect(wrapper.text()).toContain(
      "View submitted and stored BibTeX",
    );
    expect(wrapper.text()).toContain("Submitted source");
    expect(wrapper.text()).toContain("Stored BibTeX");
    await restoreButtons[0]!.trigger("click");
    expect(wrapper.text()).toContain("Restore revision 1 as a new revision?");

    await wrapper.get(".history-confirm .button-primary").trigger("click");
    await flushPromises();

    expect(historyApi.revertReference).toHaveBeenCalledWith(
      referenceId,
      1,
      2,
    );
    expect(wrapper.emitted("restored")).toEqual([[restored]]);
    wrapper.unmount();
  });

  it("ignores a stale history response after selecting another reference", async () => {
    const secondReferenceId = "b67ac241-aed7-419c-9dc7-435475808b30";
    const secondSummary = {
      ...summary,
      referenceId: secondReferenceId,
      title: "Selected paper",
    };
    const firstResponse = deferred<typeof history>();
    const secondResponse = deferred<typeof history>();
    historyApi.pageReferenceHistory.mockResolvedValue({
      items: [summary, secondSummary],
      total: 2,
      limit: 25,
      offset: 0,
    });
    historyApi.getReferenceHistory.mockImplementation(
      (requestedReferenceId: string) =>
        requestedReferenceId === referenceId
          ? firstResponse.promise
          : secondResponse.promise,
    );
    const wrapper = mount(HistoryPanel, {
      props: { authenticated: true },
      attachTo: document.body,
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get("button.history-trigger").trigger("click");
    await vi.waitFor(() => {
      expect(wrapper.findAll(".history-catalog > button")).toHaveLength(2);
    });
    await wrapper.findAll(".history-catalog > button")[1]!.trigger("click");
    secondResponse.resolve({
      ...history,
      referenceId: secondReferenceId,
      revisions: [
        {
          ...history.revisions[0]!,
          title: "Selected revision",
          actor: {
            ...history.revisions[0]!.actor,
            email: "selected@ai.cs.ehime-u.ac.jp",
          },
        },
      ],
    });
    await flushPromises();
    expect(wrapper.text()).toContain("selected@ai.cs.ehime-u.ac.jp");

    firstResponse.resolve(history);
    await flushPromises();

    expect(wrapper.text()).toContain("selected@ai.cs.ehime-u.ac.jp");
    expect(wrapper.text()).not.toContain("member@ai.cs.ehime-u.ac.jp");
    wrapper.unmount();
  });
});
