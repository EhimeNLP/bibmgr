// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  importPipelineReferences,
  registerBibtexToDatabase,
} from "../src/api/registration";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("reference registration API", () => {
  it("preserves source bytes and returns the complete registered batch", async () => {
    const first = "@article{one,\n  title = {One}\n}\n";
    const second = "@article{two,\n  title = {Two}\n}\n";
    const source = `${first}\n${second}`;
    const payload = {
      reference: {
        id: "one",
        title: "One",
        authors: [],
        bibtex: first,
        sourceRevision: `sha256:${"1".repeat(64)}`,
      },
      references: [
        {
          id: "one",
          title: "One",
          authors: [],
          bibtex: first,
          sourceRevision: `sha256:${"1".repeat(64)}`,
        },
        {
          id: "two",
          title: "Two",
          authors: [],
          bibtex: second,
          sourceRevision: `sha256:${"2".repeat(64)}`,
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload, 201));
    vi.stubGlobal("fetch", fetchMock);

    const result = await registerBibtexToDatabase({
      bibtex: source,
      source: "file",
    });

    expect(result.reference.bibtex).toBe(first);
    expect(result.references?.map((reference) => reference.bibtex)).toEqual([
      first,
      second,
    ]);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      bibtex: source,
      source: "file",
    });
  });

  it("uses the structured backend error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            schema_version: "1",
            error: {
              code: "duplicate_reference",
              message: "A matching DOI already exists.",
            },
          },
          409,
        ),
      ),
    );

    await expect(
      registerBibtexToDatabase({
        bibtex: "@article{duplicate}",
        source: "manual",
      }),
    ).rejects.toThrow("A matching DOI already exists.");
  });

  it("imports reviewed pipeline items and preserves citation contexts", async () => {
    const bibtex = "@article{pipeline, title={Pipeline result}}";
    const citationContext = {
      id: "context-1",
      sourcePaperTitle: "Source paper",
      sourceFileName: "source.json",
      context: "Pipeline result is cited here.",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          reference: {
            id: "pipeline",
            title: "Pipeline result",
            authors: [],
            bibtex,
            sourceRevision: `sha256:${"3".repeat(64)}`,
            citationContexts: [citationContext],
          },
          references: [],
        },
        201,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const items = [
      {
        bibtex,
        citation_contexts: [
          {
            source_paper_title: "Source paper",
            source_file_name: "source.json",
            context: "Pipeline result is cited here.",
          },
        ],
      },
    ];
    const result = await importPipelineReferences(items);

    expect(result.reference.citationContexts).toEqual([citationContext]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/references/pipeline-import");
    expect(JSON.parse(String(init.body))).toEqual({ items });
  });

  it("uses a brace-free display title while preserving fallback BibTeX", async () => {
    const bibtex = concatBibtex(
      "@inproceedings{gong-etal-2023-diffuseq,",
      "  title = {{D}iffu{S}eq-v2: Bridging Text Spaces},",
      "}",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ id: "diffuseq", bibtex }, 201)),
    );

    const result = await registerBibtexToDatabase({
      bibtex,
      source: "manual",
    });

    expect(result.reference.title).toBe(
      "DiffuSeq-v2: Bridging Text Spaces",
    );
    expect(result.reference.bibtex).toBe(bibtex);
  });
});

function concatBibtex(...lines: string[]): string {
  return `${lines.join("\n")}\n`;
}
