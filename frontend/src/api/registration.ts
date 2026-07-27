import type {
  Reference,
  PipelineImportItem,
  RegisterBibtexPayload,
  RegisterBibtexResult,
} from "../types/reference";
import {
  authenticatedWriteHeaders,
  handleAuthenticationFailure,
} from "./auth";

type ApiRecord = Record<string, unknown>;

const API_BASE_URL = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api"
).replace(/\/$/, "");

export async function registerBibtexToDatabase(
  payload: RegisterBibtexPayload,
): Promise<RegisterBibtexResult> {
  const response = await fetch(`${API_BASE_URL}/references`, {
    method: "POST",
    credentials: "include",
    headers: authenticatedWriteHeaders({ json: true }),
    body: JSON.stringify(payload),
  });
  const responsePayload = await readResponsePayload(response);

  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw new Error(errorMessage(responsePayload, "Failed to register BibTeX."));
  }

  return normalizeRegisterBibtexResult(responsePayload, payload.bibtex);
}

export async function importPipelineReferences(
  items: PipelineImportItem[],
): Promise<RegisterBibtexResult> {
  const response = await fetch(`${API_BASE_URL}/references/pipeline-import`, {
    method: "POST",
    credentials: "include",
    headers: authenticatedWriteHeaders({ json: true }),
    body: JSON.stringify({ items }),
  });
  const responsePayload = await readResponsePayload(response);
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw new Error(
      errorMessage(responsePayload, "Failed to import pipeline results."),
    );
  }
  return normalizeRegisterBibtexResult(
    responsePayload,
    items[0]?.bibtex ?? "",
  );
}

async function readResponsePayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  return text ? { message: text } : {};
}

function normalizeRegisterBibtexResult(
  payload: unknown,
  fallbackBibtex: string,
): RegisterBibtexResult {
  const record = asRecord(payload);
  const referenceRecord =
    asRecord(record?.reference) ??
    asRecord(record?.data) ??
    asRecord(record) ??
    {};
  const fallbackReference = referenceFromBibtex(fallbackBibtex);
  const reference = normalizeReferenceRecord(
    referenceRecord,
    fallbackReference,
    fallbackBibtex,
  );
  const references = Array.isArray(record?.references)
    ? record.references
        .map((item) => asRecord(item))
        .filter((item): item is ApiRecord => Boolean(item))
        .map((item) =>
          normalizeReferenceRecord(item, fallbackReference, fallbackBibtex),
        )
    : undefined;

  return {
    reference,
    references,
  };
}

function normalizeReferenceRecord(
  referenceRecord: ApiRecord,
  fallbackReference: Reference,
  fallbackBibtex: string,
): Reference {
  const rawCitationContexts =
    referenceRecord.citationContexts ??
    referenceRecord.citation_contexts;
  return {
    id:
      stringValue(referenceRecord.id) ??
      stringValue(referenceRecord.reference_id) ??
      stringValue(referenceRecord.referenceId) ??
      createClientId("reference"),
    title: stringValue(referenceRecord.title) ?? fallbackReference.title,
    authors: authorsValue(referenceRecord.authors) ?? fallbackReference.authors,
    year: numberValue(referenceRecord.year) ?? fallbackReference.year,
    venue: stringValue(referenceRecord.venue) ?? fallbackReference.venue,
    doi: stringValue(referenceRecord.doi) ?? fallbackReference.doi,
    url: stringValue(referenceRecord.url) ?? fallbackReference.url,
    bibtexKey:
      stringValue(referenceRecord.bibtexKey) ??
      stringValue(referenceRecord.bibtex_key) ??
      fallbackReference.bibtexKey,
    bibtex:
      rawStringValue(referenceRecord.bibtex) ??
      rawStringValue(referenceRecord.formatted_bibtex) ??
      fallbackBibtex,
    sourceRevision:
      stringValue(referenceRecord.sourceRevision) ??
      stringValue(referenceRecord.source_revision),
    citationContexts: Array.isArray(rawCitationContexts)
      ? rawCitationContexts
          .map(normalizeCitationContext)
          .filter((context) => context.id && context.context)
      : fallbackReference.citationContexts,
    createdAt:
      stringValue(referenceRecord.createdAt) ??
      stringValue(referenceRecord.created_at),
    updatedAt:
      stringValue(referenceRecord.updatedAt) ??
      stringValue(referenceRecord.updated_at),
  };
}

function normalizeCitationContext(value: unknown) {
  const record = asRecord(value) ?? {};
  return {
    id: stringValue(record.id) ?? "",
    sourcePaperTitle:
      stringValue(record.sourcePaperTitle) ??
      stringValue(record.source_paper_title),
    sourceFileName:
      stringValue(record.sourceFileName) ??
      stringValue(record.source_file_name),
    before: stringValue(record.before),
    context: stringValue(record.context) ?? "",
    after: stringValue(record.after),
  };
}

function referenceFromBibtex(bibtex: string): Reference {
  return {
    id: createClientId("reference"),
    title: extractBibtexField(bibtex, "title") ?? "Untitled reference",
    authors: authorsValue(extractBibtexField(bibtex, "author")) ?? [],
    year: numberValue(extractBibtexField(bibtex, "year")),
    venue:
      extractBibtexField(bibtex, "journal") ??
      extractBibtexField(bibtex, "booktitle"),
    doi: extractBibtexField(bibtex, "doi"),
    url: extractBibtexField(bibtex, "url"),
    bibtexKey: extractBibtexKey(bibtex),
    bibtex,
  };
}

function extractBibtexKey(bibtex: string): string | undefined {
  return bibtex.match(/@\w+\s*\{\s*([^,\s]+)\s*,/)?.[1];
}

function extractBibtexField(
  bibtex: string,
  fieldName: string,
): string | undefined {
  const pattern = new RegExp(`${fieldName}\\s*=\\s*[{\"]([^}\"]+)`, "i");
  return stringValue(bibtex.match(pattern)?.[1]);
}

function errorMessage(payload: unknown, fallback: string): string {
  const record = asRecord(payload);
  const error = asRecord(record?.error);
  return (
    stringValue(error?.message) ??
    stringValue(record?.detail) ??
    stringValue(record?.message) ??
    stringValue(record?.error) ??
    fallback
  );
}

function asRecord(value: unknown): ApiRecord | undefined {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as ApiRecord;
  }
  return undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : undefined;
}

function rawStringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  return undefined;
}

function authorsValue(value: unknown): string[] | undefined {
  if (Array.isArray(value)) {
    const authors = value
      .map((author) => stringValue(author))
      .filter((author): author is string => Boolean(author));
    return authors.length > 0 ? authors : undefined;
  }

  const authorText = stringValue(value);
  if (!authorText) {
    return undefined;
  }

  const authors = authorText
    .split(/\s+and\s+|,\s*/)
    .map((author) => author.trim())
    .filter(Boolean);
  return authors.length > 0 ? authors : undefined;
}

function createClientId(prefix: string): string {
  const randomPart =
    crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${randomPart}`;
}
