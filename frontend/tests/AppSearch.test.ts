// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App.vue";
import { getAuthenticationSession, AUTHENTICATION_REQUIRED_EVENT } from "../src/api/auth";
import { searchReferencePage } from "../src/api/references";
import type { ReferencePage } from "../src/types/reference";

vi.mock("../src/api/auth", async (original) => ({
  ...await original<typeof import("../src/api/auth")>(),
  getAuthenticationSession: vi.fn(),
}));
vi.mock("../src/api/references", async (original) => ({
  ...await original<typeof import("../src/api/references")>(),
  searchReferencePage: vi.fn(),
}));

const correction = { originalQuery: "machne learning", correctedQuery: "machine learning" };
const page: ReferencePage = {
  items: [{ id: "paper", title: "Machine learning", authors: [] }],
  total: 30, limit: 25, offset: 0,
};
const stubs = {
  AuthMenu: { template: "<div />", methods: { openLogin: vi.fn() } },
  ThemeSwitcher: true, SettingsPanel: true,
  HistoryPanel: true, RegistrationPanel: true, ReferenceDetail: true,
};
let wrapper: ReturnType<typeof mount>;

beforeEach(() => {
  vi.mocked(getAuthenticationSession).mockResolvedValue({ schema_version: "1", authenticated: true });
  vi.mocked(searchReferencePage).mockImplementation(async (filters, options) => ({
    ...page,
    offset: options?.offset ?? 0,
    correction: filters.query === correction.originalQuery && filters.searchMode !== "original"
      ? correction : undefined,
  }));
});
afterEach(() => {
  wrapper?.unmount();
  vi.resetAllMocks();
});

async function search(query: string) {
  await wrapper.get("#reference-search").setValue(query);
  await wrapper.get("form[role=search]").trigger("submit");
  await flushPromises();
}

describe("reference search correction", () => {
  it("keeps the selected spelling across pages and sorting, and resets it for a new query", async () => {
    wrapper = mount(App, { global: { stubs } });
    await flushPromises();
    await search("machne learning");
    expect(wrapper.get(".search-correction-notice").text()).toContain("Showing results for machine learning");
    await wrapper.get(".pagination button:last-child").trigger("click");
    await flushPromises();
    expect(searchReferencePage).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "machne learning", searchMode: "auto" }),
      { limit: 25, offset: 25 },
    );
    await wrapper.get(".search-correction-notice button").trigger("click");
    await flushPromises();
    expect(searchReferencePage).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "machne learning", searchMode: "original" }),
      { limit: 25, offset: 0 },
    );
    expect(wrapper.find(".search-correction-notice").exists()).toBe(false);
    await wrapper.get(".search-sort-trigger").trigger("click");
    await wrapper.findAll('[role="menuitemradio"]')[1]!.trigger("click");
    await flushPromises();
    await wrapper.get(".pagination button:last-child").trigger("click");
    await flushPromises();
    expect(searchReferencePage).toHaveBeenLastCalledWith(
      expect.objectContaining({ searchMode: "original", sort: "updated_desc" }),
      { limit: 25, offset: 25 },
    );
    await search("neural retrieval");
    expect(searchReferencePage).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "neural retrieval", searchMode: "auto" }),
      { limit: 25, offset: 0 },
    );
  });

  it("shows an empty literal result and allows automatic correction again", async () => {
    wrapper = mount(App, { global: { stubs } });
    await flushPromises();
    await search("machne learning");
    vi.mocked(searchReferencePage).mockResolvedValueOnce({ items: [], total: 0, limit: 25, offset: 0 });
    await wrapper.get(".search-correction-notice button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("No matching references found");
    expect(wrapper.text()).toContain("Searching for the original spelling");
    await wrapper.get(".search-original-notice button").trigger("click");
    await flushPromises();
    expect(wrapper.find(".search-correction-notice").exists()).toBe(true);
  });

  it("does not restore a stale correction after authentication is cleared", async () => {
    wrapper = mount(App, { global: { stubs } });
    await flushPromises();
    let resolve!: (value: ReferencePage) => void;
    vi.mocked(searchReferencePage).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await search("machne learning");
    window.dispatchEvent(new Event(AUTHENTICATION_REQUIRED_EVENT));
    resolve({ ...page, correction });
    await flushPromises();
    expect(wrapper.find(".search-correction-notice").exists()).toBe(false);
    expect(wrapper.text()).toContain("Log in to access BibMgR");
  });
});
