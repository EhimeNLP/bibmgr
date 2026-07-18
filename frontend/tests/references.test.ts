import { describe, expect, it } from "vitest";
import { searchReferences } from "../src/api/references";
import { testReferences } from "../src/data/testReferences";

describe("searchReferences", () => {
  it("returns the complete local library for an empty or whitespace-only query", async () => {
    await expect(searchReferences("   ")).resolves.toEqual(testReferences);
  });

  it.each([
    ["JACOB DEVLIN", "acl-n19-1423"],
    ["n19-1423", "acl-n19-1423"],
    ["lewis-etal-2020-bart", "acl-2020-acl-main-703"],
  ])("matches %s across searchable metadata", async (query, expectedId) => {
    const results = await searchReferences(query);

    expect(results.map((reference) => reference.id)).toContain(expectedId);
  });

  it("returns an empty result for an unknown term", async () => {
    await expect(searchReferences("definitely-not-in-the-library")).resolves.toEqual([]);
  });
});
