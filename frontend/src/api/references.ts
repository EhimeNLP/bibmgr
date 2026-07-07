import type { Reference } from "../types/reference";
import { testReferences } from "../data/testReferences";

export async function searchReferences(query: string): Promise<Reference[]> {
  const normalizedQuery = normalizeText(query);

  if (!normalizedQuery) {
    return testReferences;
  }

  return testReferences.filter((reference) =>
    normalizeText(getSearchableText(reference)).includes(normalizedQuery),
  );
}

function getSearchableText(reference: Reference): string {
  return [
    reference.title,
    ...reference.authors,
    reference.year,
    reference.venue,
    reference.doi,
    reference.url,
    reference.bibtexKey,
    reference.bibtex,
  ]
    .filter(Boolean)
    .join(" ");
}

function normalizeText(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}
