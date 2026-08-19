// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  analyzeBibtex,
  applyBibtexFixes,
  BibtexApiError,
  canonicalizeBibtexForStorage,
  exportBibtex,
  listBibtexExportProfiles,
  validateBibtexForRegistration,
} from "../src/api/bibtex";
import { AUTHENTICATION_REQUIRED_EVENT } from "../src/api/auth";

const sourceRevision = `sha256:${"0".repeat(64)}`;

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BibTeX API", () => {
  it("posts tolerant analysis without changing source bytes", async () => {
    const source = "@article{key,\r\n  title = {日本語}\r\n}";
    const payload = {
      schema_version: "1" as const,
      source_revision: sourceRevision,
      syntax: { mode: "tolerant" },
      bibliography: { records: [], diagnostics: [] },
      diagnostics: [],
      available_fixes: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      analyzeBibtex(
        { source, profile: "acl", mode: "tolerant" },
        { signal: controller.signal },
      ),
    ).resolves.toEqual(payload);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/bibtex/analyze");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.signal).toBe(controller.signal);
    expect(JSON.parse(String(init.body))).toEqual({
      source,
      profile: "acl",
      mode: "tolerant",
    });
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  });

  it("sends selected fix IDs to the dedicated fix endpoint", async () => {
    const payload = {
      schema_version: "1" as const,
      source: "@misc{key,}\n",
      source_revision: sourceRevision,
      applied_fix_ids: ["BIB-SYNTAX-004:0"],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      applyBibtexFixes({
        source: "@misc{key}",
        source_revision: sourceRevision,
        fix_ids: ["BIB-SYNTAX-004:0"],
        profile: "modern",
      }),
    ).resolves.toEqual(payload);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bibtex/fixes/apply",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("returns the authoritative registration decision", async () => {
    const payload = {
      schema_version: "1" as const,
      accepted: false,
      source_revision: sourceRevision,
      diagnostics: [],
      source: "@misc{key}",
      applied_fix_ids: [],
      unresolved_semantics: false,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      validateBibtexForRegistration({
        source: "@misc{key}",
        policy: "modern",
      }),
    ).resolves.toEqual(payload);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).policy).toBe("modern");
  });

  it("requests storage canonicalization separately from validation and export", async () => {
    const payload = {
      schema_version: "1" as const,
      accepted: true,
      source_revision: sourceRevision,
      diagnostics: [],
      source: "@misc{key,\n  title = {T},\n}\n",
      applied_fix_ids: ["BIB-SYNTAX-002:0"],
      unresolved_semantics: false,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      canonicalizeBibtexForStorage({
        source: "@misc{key, Title={T}}",
        policy: "modern",
      }),
    ).resolves.toEqual(payload);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/bibtex/registration/canonicalize",
    );
  });

  it("keeps export separate from source-preserving fixes", async () => {
    const payload = {
      schema_version: "1" as const,
      source: "@misc{key, howpublished = {arXiv:1706.03762}}\n",
      profile: "classical-bst",
      venue_name_style: "full",
      record_count: 1,
      warnings: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      exportBibtex({ source: "@article{key}", profile: "classical-bst" }),
    ).resolves.toEqual(payload);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/bibtex/export");
  });

  it("lists server-owned export profiles without hard-coding them in the client", async () => {
    const payload = {
      schema_version: "1" as const,
      profiles: [
        {
          id: "custom-profile",
          display_name: "Custom Profile",
          description: "Custom optimized BibTeX.",
          validation_profile: "modern",
          preprint_representation: "misc-eprint",
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      listBibtexExportProfiles({ signal: controller.signal }),
    ).resolves.toEqual(payload);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/bibtex/export/profiles");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.signal).toBe(controller.signal);
    expect(init.body).toBeUndefined();
  });

  it("requests login when the session is no longer valid", async () => {
    const authenticationRequired = vi.fn();
    window.addEventListener(
      AUTHENTICATION_REQUIRED_EVENT,
      authenticationRequired,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            schema_version: "1",
            error: {
              code: "authentication_required",
              message: "Login is required for this operation.",
            },
          },
          401,
        ),
      ),
    );

    await expect(listBibtexExportProfiles()).rejects.toMatchObject({
      status: 401,
      code: "authentication_required",
    });
    expect(authenticationRequired).toHaveBeenCalledOnce();
    window.removeEventListener(
      AUTHENTICATION_REQUIRED_EVENT,
      authenticationRequired,
    );
  });

  it("exposes structured backend errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          schema_version: "1",
          error: {
            code: "edit_conflict",
            message: "The source revision is stale.",
            details: { expected: sourceRevision },
          },
        },
        409,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const request = applyBibtexFixes({
      source: "changed",
      source_revision: sourceRevision,
      fix_ids: ["fix"],
    });

    await expect(request).rejects.toMatchObject({
      name: "BibtexApiError",
      code: "edit_conflict",
      status: 409,
      details: { expected: sourceRevision },
    } satisfies Partial<BibtexApiError>);
  });

  it("rejects a successful response from an unsupported schema", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ schema_version: "2" })),
    );

    await expect(
      analyzeBibtex({ source: "", mode: "tolerant" }),
    ).rejects.toMatchObject({ code: "unsupported_schema" });
  });
});
