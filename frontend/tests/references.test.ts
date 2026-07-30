// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addCitationContexts,
  deleteReference,
  getReference,
  searchReferencePage,
  searchReferences,
  updateReference,
} from "../src/api/references";
import { AUTHENTICATION_REQUIRED_EVENT } from "../src/api/auth";

const sourceRevision = `sha256:${"0".repeat(64)}`;
const reference = {
  id: "a3be35b1-6111-4e8e-8067-fecb0f642eee",
  title: "日本語解析",
  authors: ["太郎 山田"],
  year: 2024,
  venue: "TACL",
  doi: "10.1000/example",
  url: null,
  bibtexKey: "yamada2024",
  bibtex: "@article{yamada2024}\n",
  sourceRevision,
  citationContexts: [],
  createdAt: "2026-07-27T00:00:00Z",
  updatedAt: "2026-07-27T00:00:00Z",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("reference library API", () => {
  it("searches the backend library and normalizes its response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([reference]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(searchReferences("  山田  ")).resolves.toEqual([
      {
        ...reference,
        url: undefined,
      },
    ]);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/references?query=%E5%B1%B1%E7%94%B0&limit=100");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
  });

  it("removes BibTeX case-protection braces from display titles", async () => {
    const protectedTitle = {
      ...reference,
      title:
        "{D}iffu{S}eq-v2: Bridging Discrete and Continuous Text Spaces",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse([protectedTitle])),
    );

    await expect(searchReferences("diffuseq")).resolves.toEqual([
      expect.objectContaining({
        title:
          "DiffuSeq-v2: Bridging Discrete and Continuous Text Spaces",
        bibtex: reference.bibtex,
      }),
    ]);
  });

  it("loads one reference by ID", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(reference));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getReference(reference.id)).resolves.toMatchObject({
      id: reference.id,
      sourceRevision,
      bibtex: "@article{yamada2024}\n",
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/references/${reference.id}`,
    );
  });

  it("sends structured filters and normalizes a page", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [reference],
        total: 41,
        limit: 25,
        offset: 25,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      searchReferencePage(
        {
          query: " semantics ",
          year: 2024,
          author: " 山田 ",
          identifier: "10.1000/example",
          sort: "year_desc",
        },
        { limit: 25, offset: 25 },
      ),
    ).resolves.toMatchObject({ total: 41, limit: 25, offset: 25 });

    const url = String(fetchMock.mock.calls[0]?.[0]);
    const parameters = new URL(url, "https://bibmgr.test").searchParams;
    expect(parameters.get("query")).toBe("semantics");
    expect(parameters.get("year")).toBe("2024");
    expect(parameters.get("author")).toBe("山田");
    expect(parameters.get("identifier")).toBe("10.1000/example");
    expect(parameters.get("sort")).toBe("year_desc");
    expect(parameters.get("offset")).toBe("25");
  });

  it("updates a reference with its stored source revision", async () => {
    const updated = { ...reference, title: "日本語意味解析" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(updated));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      updateReference(reference.id, {
        bibtex: "@article{yamada2024, title={日本語意味解析}}",
        source_revision: sourceRevision,
      }),
    ).resolves.toMatchObject({ title: "日本語意味解析" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({
      bibtex: "@article{yamada2024, title={日本語意味解析}}",
      source_revision: sourceRevision,
    });
  });

  it("deletes a reference using the resource endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      deleteReference(reference.id, sourceRevision),
    ).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/references/${reference.id}`,
      expect.objectContaining({ method: "DELETE" }),
    );
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("If-Match")).toBe(
      `"${sourceRevision}"`,
    );
  });

  it("adds citation contexts using the structured API", async () => {
    const contextualized = {
      ...reference,
      citationContexts: [
        {
          id: "context-1",
          sourcePaperTitle: "Citing paper",
          context: "Prior work uses this method.",
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(contextualized));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      addCitationContexts(reference.id, [
        {
          sourcePaperTitle: "Citing paper",
          context: "Prior work uses this method.",
        },
      ]),
    ).resolves.toMatchObject({
      citationContexts: [
        {
          id: "context-1",
          sourcePaperTitle: "Citing paper",
          context: "Prior work uses this method.",
        },
      ],
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      contexts: [
        {
          source_paper_title: "Citing paper",
          context: "Prior work uses this method.",
        },
      ],
    });
  });

  it("exposes structured conflict responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            schema_version: "1",
            error: {
              code: "stale_reference",
              message: "The reference has changed.",
              details: { source_revision: sourceRevision },
            },
          },
          409,
        ),
      ),
    );

    await expect(
      updateReference(reference.id, {
        bibtex: "@article{changed}",
        source_revision: sourceRevision,
      }),
    ).rejects.toMatchObject({
      name: "BibtexApiError",
      code: "stale_reference",
      status: 409,
      details: { source_revision: sourceRevision },
    });
  });

  it("requests login when a reference read returns 401", async () => {
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

    await expect(searchReferencePage({ query: "" })).rejects.toMatchObject({
      status: 401,
      code: "authentication_required",
    });
    expect(authenticationRequired).toHaveBeenCalledOnce();
    window.removeEventListener(
      AUTHENTICATION_REQUIRED_EVENT,
      authenticationRequired,
    );
  });
});
