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
});
