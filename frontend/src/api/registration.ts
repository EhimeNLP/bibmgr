import type {
  Reference,
  RegisterBibtexPayload,
  RegisterBibtexResult,
} from "../types/reference";

type ApiRecord = Record<string, unknown>;

const API_BASE_URL = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api"
).replace(/\/$/, "");
const API_KEY = import.meta.env.VITE_BIBMGR_API_KEY as string | undefined;

export async function registerBibtexToDatabase(
  payload: RegisterBibtexPayload,
): Promise<RegisterBibtexResult> {
  const response = await fetch(`${API_BASE_URL}/references`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const responsePayload = await readResponsePayload(response);

  if (!response.ok) {
    throw new Error(errorMessage(responsePayload, "Failed to register BibTeX."));
  }

  return normalizeRegisterBibtexResult(responsePayload, payload.bibtex);
}

function authHeaders(): Headers {
  const headers = new Headers();
  if (API_KEY) {
    headers.set("X-API-Key", API_KEY);
  }
  return headers;
}

function jsonHeaders(): Headers {
  const headers = authHeaders();
  headers.set("Content-Type", "application/json");
  return headers;
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

  return {
    reference: {
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
        stringValue(referenceRecord.bibtex) ??
        stringValue(referenceRecord.formatted_bibtex) ??
        fallbackBibtex,
      citationContexts: fallbackReference.citationContexts,
    },
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
  return (
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
