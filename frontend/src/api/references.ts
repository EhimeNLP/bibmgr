import type {
  CitationContextInput,
  Reference,
  ReferencePage,
  ReferenceSearchFilters,
  UpdateReferencePayload,
} from "../types/reference";
import {
  authenticatedWriteHeaders,
  handleAuthenticationFailure,
} from "./auth";
import { API_BASE_URL } from "./base";
import { BibtexApiError } from "./bibtex";
import { bibtexTitleForDisplay } from "../utils/bibtexDisplay";

export async function searchReferences(query: string): Promise<Reference[]> {
  const parameters = new URLSearchParams({
    query: query.trim(),
    limit: "100",
  });
  const response = await fetch(
    `${API_BASE_URL}/references?${parameters.toString()}`,
    { method: "GET" },
  );
  const payload = await readResponsePayload(response);

  if (!response.ok) {
    throw referenceApiError(payload, response.status);
  }
  if (!Array.isArray(payload)) {
    throw new BibtexApiError("Invalid reference search response.", {
      code: "invalid_reference_response",
      status: response.status,
    });
  }
  return payload.map(normalizeReference);
}

export async function searchReferencePage(
  filters: ReferenceSearchFilters,
  options: { limit?: number; offset?: number } = {},
): Promise<ReferencePage> {
  const parameters = new URLSearchParams();
  appendParameter(parameters, "query", filters.query?.trim());
  appendParameter(parameters, "year", filters.year);
  appendParameter(parameters, "author", filters.author?.trim());
  appendParameter(parameters, "venue", filters.venue?.trim());
  appendParameter(parameters, "identifier", filters.identifier?.trim());
  appendParameter(parameters, "entry_type", filters.entryType?.trim());
  appendParameter(parameters, "created_by", filters.createdBy?.trim());
  appendParameter(parameters, "updated_from", filters.updatedFrom);
  appendParameter(parameters, "updated_to", filters.updatedTo);
  appendParameter(parameters, "sort", filters.sort ?? "updated_desc");
  appendParameter(parameters, "limit", options.limit ?? 25);
  appendParameter(parameters, "offset", options.offset ?? 0);
  const response = await fetch(
    `${API_BASE_URL}/references/page?${parameters.toString()}`,
    { method: "GET" },
  );
  const payload = await readResponsePayload(response);
  if (!response.ok) {
    throw referenceApiError(payload, response.status);
  }
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    typeof payload.total !== "number" ||
    typeof payload.limit !== "number" ||
    typeof payload.offset !== "number"
  ) {
    throw new BibtexApiError("Invalid reference page response.", {
      code: "invalid_reference_response",
      status: response.status,
    });
  }
  return {
    items: payload.items.map(normalizeReference),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

export async function getReference(referenceId: string): Promise<Reference> {
  const response = await fetch(
    `${API_BASE_URL}/references/${encodeURIComponent(referenceId)}`,
    { method: "GET" },
  );
  return referenceResponse(response);
}

export async function updateReference(
  referenceId: string,
  payload: UpdateReferencePayload,
): Promise<Reference> {
  const response = await fetch(
    `${API_BASE_URL}/references/${encodeURIComponent(referenceId)}`,
    {
      method: "PUT",
      credentials: "include",
      headers: authenticatedWriteHeaders({ json: true }),
      body: JSON.stringify(payload),
    },
  );
  return referenceResponse(response);
}

export async function deleteReference(
  referenceId: string,
  sourceRevision: string,
): Promise<void> {
  const headers = authenticatedWriteHeaders();
  headers.set("If-Match", `"${sourceRevision}"`);
  const response = await fetch(
    `${API_BASE_URL}/references/${encodeURIComponent(referenceId)}`,
    {
      method: "DELETE",
      credentials: "include",
      headers,
    },
  );
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    const payload = await readResponsePayload(response);
    throw referenceApiError(payload, response.status);
  }
}

export async function addCitationContexts(
  referenceId: string,
  contexts: CitationContextInput[],
): Promise<Reference> {
  const response = await fetch(
    `${API_BASE_URL}/references/${encodeURIComponent(referenceId)}/citation-contexts`,
    {
      method: "POST",
      credentials: "include",
      headers: authenticatedWriteHeaders({ json: true }),
      body: JSON.stringify({
        contexts: contexts.map((context) => ({
          source_paper_title: context.sourcePaperTitle,
          source_file_name: context.sourceFileName,
          before: context.before,
          context: context.context,
          after: context.after,
        })),
      }),
    },
  );
  return referenceResponse(response);
}

async function referenceResponse(response: Response): Promise<Reference> {
  const payload = await readResponsePayload(response);
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw referenceApiError(payload, response.status);
  }
  if (!isRecord(payload)) {
    throw new BibtexApiError("Invalid reference response.", {
      code: "invalid_reference_response",
      status: response.status,
    });
  }
  return normalizeReference(payload);
}

function normalizeReference(value: unknown): Reference {
  const record = isRecord(value) ? value : {};
  const rawCitationContexts =
    record.citationContexts ?? record.citation_contexts;
  return {
    id: stringValue(record.id) ?? "",
    title: bibtexTitleForDisplay(
      stringValue(record.title) ?? "Untitled reference",
    ),
    authors: Array.isArray(record.authors)
      ? record.authors.filter((author): author is string => typeof author === "string")
      : [],
    year: numberValue(record.year),
    venue: stringValue(record.venue),
    doi: stringValue(record.doi),
    url: stringValue(record.url),
    bibtexKey:
      stringValue(record.bibtexKey) ?? stringValue(record.bibtex_key),
    bibtex: stringValue(record.bibtex),
    sourceRevision:
      stringValue(record.sourceRevision) ??
      stringValue(record.source_revision),
    citationContexts: Array.isArray(rawCitationContexts)
      ? rawCitationContexts
          .map(normalizeCitationContext)
          .filter((context) => context.id && context.context)
      : undefined,
    createdAt:
      stringValue(record.createdAt) ?? stringValue(record.created_at),
    updatedAt:
      stringValue(record.updatedAt) ?? stringValue(record.updated_at),
  };
}

function normalizeCitationContext(value: unknown) {
  const record = isRecord(value) ? value : {};
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

async function readResponsePayload(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return undefined;
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  const text = await response.text();
  return text ? { message: text } : {};
}

function referenceApiError(
  payload: unknown,
  status: number,
): BibtexApiError {
  const record = isRecord(payload) ? payload : undefined;
  const error = isRecord(record?.error) ? record.error : undefined;
  return new BibtexApiError(
    stringValue(error?.message) ??
      stringValue(record?.message) ??
      `Reference request failed with status ${status}.`,
    {
      code: stringValue(error?.code) ?? "reference_request_failed",
      status,
      details: isRecord(error?.details) ? error.details : undefined,
    },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function appendParameter(
  parameters: URLSearchParams,
  name: string,
  value: string | number | undefined,
) {
  if (value === undefined || value === "") return;
  parameters.set(name, String(value));
}
