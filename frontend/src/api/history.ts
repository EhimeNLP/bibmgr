import type {
  ReferenceHistory,
  ReferenceHistoryAction,
  ReferenceHistoryPage,
  ReferenceHistorySummary,
  ReferenceRevision,
} from "../types/history";
import type { Reference } from "../types/reference";
import {
  authenticatedWriteHeaders,
  handleAuthenticationFailure,
} from "./auth";
import { BibtexApiError } from "./bibtex";

const API_BASE_URL = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api"
).replace(/\/$/, "");

const HISTORY_ACTIONS = new Set<ReferenceHistoryAction>([
  "baseline",
  "create",
  "update",
  "delete",
  "restore",
  "context",
]);

export async function listReferenceHistory(): Promise<
  ReferenceHistorySummary[]
> {
  const response = await fetch(`${API_BASE_URL}/reference-history`, {
    method: "GET",
    credentials: "include",
  });
  const payload = await readPayload(response);
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw historyError(payload, response.status);
  }
  if (!Array.isArray(payload)) {
    throw historyError(payload, response.status, "Invalid history list.");
  }
  return payload.map(normalizeSummary);
}

export async function pageReferenceHistory(
  options: { limit?: number; offset?: number } = {},
): Promise<ReferenceHistoryPage> {
  const parameters = new URLSearchParams({
    limit: String(options.limit ?? 25),
    offset: String(options.offset ?? 0),
  });
  const response = await fetch(
    `${API_BASE_URL}/reference-history/page?${parameters.toString()}`,
    { method: "GET", credentials: "include" },
  );
  const payload = await readPayload(response);
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw historyError(payload, response.status);
  }
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    typeof payload.total !== "number" ||
    typeof payload.limit !== "number" ||
    typeof payload.offset !== "number"
  ) {
    throw historyError(payload, response.status, "Invalid history page.");
  }
  return {
    items: payload.items.map(normalizeSummary),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

export async function getReferenceHistory(
  referenceId: string,
): Promise<ReferenceHistory> {
  const response = await fetch(
    `${API_BASE_URL}/references/${encodeURIComponent(referenceId)}/history`,
    { method: "GET", credentials: "include" },
  );
  const payload = await readPayload(response);
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw historyError(payload, response.status);
  }
  return normalizeHistory(payload);
}

export async function revertReference(
  referenceId: string,
  targetRevision: number,
  expectedHeadRevision: number,
): Promise<Reference> {
  const response = await fetch(
    `${API_BASE_URL}/references/${encodeURIComponent(referenceId)}/revert`,
    {
      method: "POST",
      credentials: "include",
      headers: authenticatedWriteHeaders({ json: true }),
      body: JSON.stringify({
        target_revision: targetRevision,
        expected_head_revision: expectedHeadRevision,
      }),
    },
  );
  const payload = await readPayload(response);
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw historyError(payload, response.status);
  }
  return normalizeReference(payload);
}

function normalizeSummary(value: unknown): ReferenceHistorySummary {
  const record = requiredRecord(value, "Invalid history summary.");
  return {
    referenceId: requiredString(record.referenceId),
    headRevision: requiredNumber(record.headRevision),
    exists: requiredBoolean(record.exists),
    title: optionalString(record.title),
    latestAction: requiredAction(record.latestAction),
    updatedAt: requiredString(record.updatedAt),
  };
}

function normalizeHistory(value: unknown): ReferenceHistory {
  const record = requiredRecord(value, "Invalid reference history.");
  if (!Array.isArray(record.revisions)) {
    throw new Error("Invalid reference history revisions.");
  }
  return {
    referenceId: requiredString(record.referenceId),
    headRevision: requiredNumber(record.headRevision),
    exists: requiredBoolean(record.exists),
    revisions: record.revisions.map(normalizeRevision),
  };
}

function normalizeRevision(value: unknown): ReferenceRevision {
  const record = requiredRecord(value, "Invalid reference revision.");
  const actor = requiredRecord(record.actor, "Invalid revision actor.");
  return {
    revision: requiredNumber(record.revision),
    action: requiredAction(record.action),
    actor: {
      id: requiredString(actor.id),
      email: requiredString(actor.email),
    },
    occurredAt: requiredString(record.occurredAt),
    restoredFromRevision: optionalNumber(record.restoredFromRevision),
    title: optionalString(record.title),
    sourceRevision: optionalString(record.sourceRevision),
    submittedBibtex: optionalString(record.submittedBibtex),
    canonicalBibtex: optionalString(record.canonicalBibtex),
    restorable: requiredBoolean(record.restorable),
  };
}

function normalizeReference(value: unknown): Reference {
  const record = requiredRecord(value, "Invalid restored reference.");
  const citationContexts =
    record.citationContexts ?? record.citation_contexts;
  return {
    id: requiredString(record.id),
    title: requiredString(record.title),
    authors: Array.isArray(record.authors)
      ? record.authors.filter(
          (author): author is string => typeof author === "string",
        )
      : [],
    year: optionalNumber(record.year),
    venue: optionalString(record.venue),
    doi: optionalString(record.doi),
    url: optionalString(record.url),
    bibtexKey:
      optionalString(record.bibtexKey) ??
      optionalString(record.bibtex_key),
    bibtex: optionalString(record.bibtex),
    sourceRevision:
      optionalString(record.sourceRevision) ??
      optionalString(record.source_revision),
    citationContexts: Array.isArray(citationContexts)
      ? citationContexts
          .map(normalizeCitationContext)
          .filter((context) => context.id && context.context)
      : [],
    createdAt:
      optionalString(record.createdAt) ??
      optionalString(record.created_at),
    updatedAt:
      optionalString(record.updatedAt) ??
      optionalString(record.updated_at),
  };
}

function normalizeCitationContext(value: unknown) {
  const record = requiredRecord(value, "Invalid citation context.");
  return {
    id: optionalString(record.id) ?? "",
    sourcePaperTitle:
      optionalString(record.sourcePaperTitle) ??
      optionalString(record.source_paper_title),
    sourceFileName:
      optionalString(record.sourceFileName) ??
      optionalString(record.source_file_name),
    before: optionalString(record.before),
    context: optionalString(record.context) ?? "",
    after: optionalString(record.after),
  };
}

async function readPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return undefined;
  return response.json();
}

function historyError(
  payload: unknown,
  status: number,
  fallback = `History request failed with status ${status}.`,
): BibtexApiError {
  const record = isRecord(payload) ? payload : undefined;
  const error = isRecord(record?.error) ? record.error : undefined;
  return new BibtexApiError(
    optionalString(error?.message) ??
      optionalString(record?.message) ??
      fallback,
    {
      code: optionalString(error?.code) ?? "history_request_failed",
      status,
      details: isRecord(error?.details) ? error.details : undefined,
    },
  );
}

function requiredRecord(
  value: unknown,
  message: string,
): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(message);
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown): string {
  const normalized = optionalString(value);
  if (!normalized) throw new Error("Invalid history string.");
  return normalized;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function requiredNumber(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error("Invalid history number.");
  }
  return value;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value)
    ? value
    : undefined;
}

function requiredBoolean(value: unknown): boolean {
  if (typeof value !== "boolean") {
    throw new Error("Invalid history boolean.");
  }
  return value;
}

function requiredAction(value: unknown): ReferenceHistoryAction {
  if (
    typeof value !== "string" ||
    !HISTORY_ACTIONS.has(value as ReferenceHistoryAction)
  ) {
    throw new Error("Invalid history action.");
  }
  return value as ReferenceHistoryAction;
}
