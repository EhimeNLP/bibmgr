// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { previewExportProfile } from "../src/api/configuration";
import type { ExportProfileData } from "../src/types/configuration";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("configuration API", () => {
  it("previews an unsaved profile without write authentication headers", async () => {
    const profile: ExportProfileData = {
      schema_version: "1",
      profile: "custom-profile",
      display_name: "Custom Profile",
      description: "Custom output.",
      validation_profile: "modern",
      preprint_representation: "misc-eprint",
      month_format: "numeric",
      supported_entry_types: [],
      field_order: ["title"],
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
        allowed_fields: ["title"],
        excluded_fields: [],
      },
      excluded_fields: [],
      allow_unknown_work_type: false,
    };
    const payload = {
      schema_version: "1",
      source: "@misc{preview, title={{Preview}}}",
      profile: "custom-profile",
      venue_name_style: "full",
      record_count: 1,
      warnings: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      previewExportProfile(
        {
          source: "@misc{preview, title={Preview}}",
          data: profile,
          venue_name_style: "full",
        },
        controller.signal,
      ),
    ).resolves.toEqual(payload);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/settings/export-profiles/preview");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.signal).toBe(controller.signal);
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBeNull();
    expect(JSON.parse(String(init.body))).toEqual({
      source: "@misc{preview, title={Preview}}",
      data: profile,
      venue_name_style: "full",
    });
  });
});
