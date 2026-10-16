// @vitest-environment jsdom
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import DuplicateReview from "../src/components/DuplicateReview.vue";
import type { DuplicateFinding } from "../src/api/duplicates";
const api = vi.hoisted(() => ({ getReference: vi.fn() }));
vi.mock("../src/api/references", () => api);
beforeEach(() => api.getReference.mockReset());
const match = (incoming: number, candidate: number, existing = false): DuplicateFinding => ({
  incoming_index: incoming, candidate_index: candidate, existing,
  ...(existing ? { reference_id: `stored-${candidate}` } : {}),
  title: `Study ${candidate}`, action: "reject", comparison: { kind: "exact", fields: [] },
});
it("keeps fetched BibTeX beside each match and caches it across toggles", async () => {
  api.getReference.mockImplementation(async (id: string) => ({ bibtex: `@misc{${id}}` }));
  const wrapper = mount(DuplicateReview, { props: { findings: [match(0, 0, true), match(1, 1, true)] } });
  const articles = wrapper.findAll("article");
  for (const article of articles) await article.get("button").trigger("click");
  await flushPromises();
  expect(articles[0]!.get("pre").text()).toBe("@misc{stored-0}");
  expect(articles[1]!.get("pre").text()).toBe("@misc{stored-1}");
  await articles[0]!.get("button").trigger("click");
  expect(articles[0]!.find("pre").exists()).toBe(false);
  expect(articles[1]!.find("pre").exists()).toBe(true);
  await articles[0]!.get("button").trigger("click");
  expect(api.getReference).toHaveBeenCalledTimes(2);
  expect(wrapper.find('[aria-label="Remove input entry 1"]').exists()).toBe(false);
});
it("discards old preview responses when the reviewed input changes", async () => {
  let resolve!: (value: { bibtex: string }) => void;
  api.getReference.mockReturnValue(new Promise(done => { resolve = done; }));
  const wrapper = mount(DuplicateReview, { props: { findings: [match(0, 0, true)] } });
  await wrapper.get("article button").trigger("click");
  await wrapper.setProps({ findings: [match(0, 1, true)] });
  resolve({ bibtex: "stale" });
  await flushPromises();
  expect(wrapper.text()).not.toContain("stale");
});
