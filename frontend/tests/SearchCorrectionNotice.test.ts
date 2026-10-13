// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SearchCorrectionNotice from "../src/components/SearchCorrectionNotice.vue";

describe("SearchCorrectionNotice", () => {
  it("emphasizes changed words and lets the user search the original spelling", async () => {
    const wrapper = mount(SearchCorrectionNotice, { props: {
      correction: { originalQuery: "machne learning", correctedQuery: "machine learning" },
    } });
    expect(wrapper.get("p").text()).toBe("Showing results for machine learning");
    expect(wrapper.get("p strong em").text()).toBe("machine");
    expect(wrapper.get("button").text()).toBe("Search instead for machne learning");
    expect(wrapper.get("button strong em").text()).toBe("machne");
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("search-original")).toEqual([[]]);
  });

  it("renders Japanese and markup as text", () => {
    const wrapper = mount(SearchCorrectionNotice, { props: {
      correction: { originalQuery: "しぜんげご <script>query</script>", correctedQuery: "しぜんげんご <script>query</script>" },
    } });
    expect(wrapper.get("p").text()).toContain("しぜんげんご <script>query</script>");
    expect(wrapper.get("button").text()).toContain("しぜんげご <script>query</script>");
    expect(wrapper.find("script").exists()).toBe(false);
  });
});
