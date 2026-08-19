// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SearchBar from "../src/components/SearchBar.vue";

describe("SearchBar", () => {
  it("emits model updates and a search request on submit", async () => {
    const wrapper = mount(SearchBar, {
      props: { modelValue: "" },
    });

    await wrapper.get("input").setValue("transformer");
    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("update:modelValue")).toEqual([["transformer"]]);
    expect(wrapper.emitted("search")).toHaveLength(1);
  });

  it("announces and locks its loading state", () => {
    const wrapper = mount(SearchBar, {
      props: {
        modelValue: "transformer",
        disabled: true,
        loading: true,
      },
    });

    expect(wrapper.get("form").attributes("aria-busy")).toBe("true");
    expect(wrapper.get("input").attributes()).toHaveProperty("disabled");
    expect(wrapper.get("button").attributes()).toMatchObject({
      "aria-busy": "true",
      disabled: "",
    });
    expect(wrapper.get("button").text()).toBe("Searching…");
  });

  it("presents advanced filters in a focused popover", async () => {
    const wrapper = mount(SearchBar, {
      props: { modelValue: "vision" },
      attachTo: document.body,
    });

    await wrapper.get(".search-filter-trigger").trigger("click");

    expect(wrapper.get(".search-filter-trigger").attributes("aria-expanded")).toBe(
      "true",
    );
    expect(wrapper.get(".search-filter-panel").text()).toContain("Publication");
    expect(wrapper.get(".search-filter-panel").text()).toContain(
      "Library activity",
    );
    expect(wrapper.get(".search-filter-panel").text()).not.toContain("Order");

    const year = wrapper.get<HTMLInputElement>('input[placeholder="Any year"]');
    const author = wrapper.get<HTMLInputElement>(
      'input[placeholder="Any author"]',
    );
    await year.setValue("2025");
    await author.setValue("Yoneyama");
    await wrapper.get(".search-filter-apply").trigger("submit");

    expect(wrapper.emitted("search")?.at(-1)?.[0]).toMatchObject({
      query: "vision",
      year: 2025,
      author: "Yoneyama",
      sort: "updated_desc",
    });
    expect(wrapper.find(".search-filter-panel").exists()).toBe(false);
    expect(wrapper.findAll(".search-token")).toHaveLength(2);
    expect(wrapper.get(".search-filter-trigger").attributes("aria-label")).toBe(
      "Show search filters, 2 active",
    );

    wrapper.unmount();
  });

  it("applies sorting independently from filters", async () => {
    const wrapper = mount(SearchBar, {
      props: { modelValue: "vision" },
      attachTo: document.body,
    });

    const trigger = wrapper.get(".search-sort-trigger");
    expect(trigger.attributes("aria-label")).toBe(
      "Sort references: Recently Updated",
    );

    await trigger.trigger("click");

    const menu = wrapper.get('[role="menu"][aria-label="Sort references"]');
    const options = menu.findAll('[role="menuitemradio"]');
    expect(options.map((option) => option.text())).toEqual([
      "Recently Updated",
      "Oldest Update",
      "Newest Publication",
      "Oldest Publication",
      "Title A–Z",
    ]);
    expect(options[0]?.attributes("aria-checked")).toBe("true");

    await options[2]?.trigger("click");

    expect(wrapper.emitted("search")?.at(-1)?.[0]).toMatchObject({
      query: "vision",
      sort: "year_desc",
    });
    expect(wrapper.find('[role="menu"]').exists()).toBe(false);
    expect(wrapper.find(".search-token").exists()).toBe(false);
    expect(trigger.attributes("aria-label")).toBe(
      "Sort references: Newest Publication",
    );

    wrapper.unmount();
  });

  it("removes a visible filter token and refreshes results", async () => {
    const wrapper = mount(SearchBar, {
      props: { modelValue: "" },
    });

    await wrapper.get(".search-filter-trigger").trigger("click");
    await wrapper
      .get<HTMLInputElement>('input[placeholder="Journal or conference"]')
      .setValue("CHI");
    await wrapper.get(".search-filter-apply").trigger("submit");
    await wrapper.get(".search-token").trigger("click");

    expect(wrapper.find(".search-token").exists()).toBe(false);
    expect(wrapper.emitted("search")?.at(-1)?.[0]).toMatchObject({
      venue: "",
    });
  });

  it("does not present dismissed draft filters as active", async () => {
    const wrapper = mount(SearchBar, {
      props: { modelValue: "" },
    });

    await wrapper.get(".search-filter-trigger").trigger("click");
    await wrapper
      .get<HTMLInputElement>('input[placeholder="Any author"]')
      .setValue("Draft Author");
    await wrapper.get(".search-filter-panel__close").trigger("click");

    expect(wrapper.find(".search-token").exists()).toBe(false);

    await wrapper.get(".search-filter-trigger").trigger("click");
    expect(
      wrapper.get<HTMLInputElement>('input[placeholder="Any author"]').element
        .value,
    ).toBe("");
  });
});
