// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ExportProfileEditor from "../src/components/ExportProfileEditor.vue";
import type { ExportProfileData } from "../src/types/configuration";

const apiMocks = vi.hoisted(() => ({
  previewExportProfile: vi.fn(),
}));

vi.mock("../src/api/configuration", () => apiMocks);

const profile: ExportProfileData = {
  schema_version: "1",
  profile: "laboratory",
  display_name: "Laboratory",
  description: "Laboratory output.",
  validation_profile: "laboratory",
  preprint_representation: "misc-eprint",
  month_format: "numeric",
  supported_entry_types: [],
  field_order: ["title", "author", "booktitle", "year", "doi", "url"],
  field_case: "canonical",
  case_protected_fields: ["title"],
  value_delimiter: "braces",
  line_ending: "lf",
  indent: "  ",
  trailing_comma: true,
  include_doi: true,
  include_url: true,
  include_extra_fields: true,
  field_renames: {},
  field_selection: {
    allowed_fields: ["title", "author", "booktitle", "year", "doi", "url"],
    excluded_fields: [],
  },
  excluded_fields: [],
  allow_unknown_work_type: false,
};

beforeEach(() => {
  vi.useFakeTimers();
  apiMocks.previewExportProfile.mockReset();
  apiMocks.previewExportProfile.mockResolvedValue({
    schema_version: "1",
    source: "@misc{preview,\\n  title = {{Preview}},\\n}",
    profile: "laboratory",
    venue_name_style: "full",
    record_count: 1,
    warnings: [],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ExportProfileEditor", () => {
  it("represents the fixed profile schema with semantic controls", async () => {
    const wrapper = controlledMount();

    expect(wrapper.text()).toContain("Profile details");
    expect(wrapper.text()).toContain("Output fields");
    expect(wrapper.text()).toContain("BibTeX formatting");
    expect(wrapper.text()).toContain("Supported entry types");
    expect(wrapper.text()).not.toContain("Profile definition (JSON)");
    expect(wrapper.find('textarea[spellcheck="false"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="export-profile-json"]').text()).toContain(
      '"field_selection"',
    );

    await wrapper
      .get('input[aria-label="Include title"]')
      .setValue(false);
    expect(
      (wrapper.props("modelValue") as ExportProfileData).field_selection
        .allowed_fields,
    ).not.toContain("title");

    await wrapper
      .get('input[aria-label="Protect author from case changes"]')
      .setValue(true);
    expect(
      (wrapper.props("modelValue") as ExportProfileData).case_protected_fields,
    ).toContain("author");

    await wrapper
      .get('input[aria-label="Export name for doi"]')
      .setValue("identifier");
    expect(
      (wrapper.props("modelValue") as ExportProfileData).field_renames,
    ).toEqual({ doi: "identifier" });

    wrapper.unmount();
  });

  it("previews unsaved form changes without saving them", async () => {
    const wrapper = controlledMount();

    await vi.advanceTimersByTimeAsync(301);
    await flushPromises();

    expect(apiMocks.previewExportProfile).toHaveBeenCalledTimes(1);
    expect(apiMocks.previewExportProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          profile: "laboratory",
          display_name: "Laboratory",
        }),
      }),
      expect.any(AbortSignal),
    );
    expect(wrapper.get('[data-testid="export-profile-preview"]').text()).toContain(
      "Preview",
    );

    await wrapper.get('input[required]').setValue("Lab Compact");
    await vi.advanceTimersByTimeAsync(301);
    await flushPromises();

    expect(apiMocks.previewExportProfile).toHaveBeenLastCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ display_name: "Lab Compact" }),
      }),
      expect.any(AbortSignal),
    );
    expect(wrapper.emitted("update:modelValue")).not.toBeUndefined();

    wrapper.unmount();
  });

  it("applies selection and ordering to a renamed output field", async () => {
    const renamedProfile: ExportProfileData = {
      ...structuredClone(profile),
      field_order: ["title", "identifier"],
      field_renames: { doi: "identifier" },
      field_selection: {
        allowed_fields: ["title", "identifier"],
        excluded_fields: [],
      },
    };
    const wrapper = controlledMount(renamedProfile);

    expect(
      (wrapper.get('input[aria-label="Export name for doi"]').element as HTMLInputElement)
        .value,
    ).toBe("identifier");
    expect(
      wrapper.find('input[aria-label="Include doi"]').exists(),
    ).toBe(false);
    expect(
      wrapper.findAll('input[aria-label="Include identifier"]'),
    ).toHaveLength(1);

    await wrapper
      .get('input[aria-label="Include identifier"]')
      .setValue(false);
    expect(
      (wrapper.props("modelValue") as ExportProfileData).field_selection
        .allowed_fields,
    ).toEqual(["title"]);

    wrapper.unmount();
  });
});

function controlledMount(initialProfile = profile) {
  const wrapper = mount(ExportProfileEditor, {
    props: {
      modelValue: structuredClone(initialProfile),
      profileId: "laboratory",
      "onUpdate:modelValue": (value: ExportProfileData) =>
        wrapper.setProps({ modelValue: value }),
    },
  });
  return wrapper;
}
