// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { registerBibtexToDatabase } from "../src/api/registration";

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
  it.each(["journal", "booktitle"])("removes protection from fallback %s without changing BibTeX", async field => {
    const bibtex = `@article{a,title={Paper},${field}={{Venue of {NLP}}}}`;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ id: "a" }, 201)));
    const result = await registerBibtexToDatabase({ bibtex, source: "manual" });
    expect(result.reference.venue).toBe("Venue of NLP");
    expect(result.reference.bibtex).toBe(bibtex);
  });

  it("preserves literal braces in a venue already formatted by the backend", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ id: "a", venue: "Venue {Series}" }, 201)));
    const result = await registerBibtexToDatabase({ bibtex: "@article{a,title={Paper}}", source: "manual" });
    expect(result.reference.venue).toBe("Venue {Series}");
  });

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


it("preserves duplicate review details and server-issued confirmation tokens", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: {
    code: "duplicate_confirmation_required", details: { duplicates: [], confirmation_token: "a".repeat(64) },
  } }, 409)));
  await expect(registerBibtexToDatabase({ bibtex: "@misc{a}", source: "manual" })).rejects.toMatchObject({
    name: "DuplicateReviewError", findings: [], confirmationToken: "a".repeat(64),
  });
});
