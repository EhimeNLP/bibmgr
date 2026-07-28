import type {
  AnalyzeBibtexRequest,
  ApplyBibtexFixesRequest,
  ApplyBibtexFixesResult,
  BibmgrErrorResponse,
  BibtexAnalysisResult,
  BibtexExportProfilesResult,
  BibtexExportResult,
  ExportBibtexRequest,
  RegistrationValidationResult,
  ValidateRegistrationRequest,
} from "../types/bibtex";
import { API_BASE_URL } from "./base";

export type BibtexRequestOptions = {
  signal?: AbortSignal;
};

export class BibtexApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;

  constructor(
    message: string,
    options: {
      code: string;
      status: number;
      details?: Record<string, unknown>;
    },
  ) {
    super(message);
    this.name = "BibtexApiError";
    this.code = options.code;
    this.status = options.status;
    this.details = options.details;
  }
}

export function analyzeBibtex(
  request: AnalyzeBibtexRequest,
  options?: BibtexRequestOptions,
): Promise<BibtexAnalysisResult> {
  return postVersionedJson("/bibtex/analyze", request, options);
}

export function applyBibtexFixes(
  request: ApplyBibtexFixesRequest,
  options?: BibtexRequestOptions,
): Promise<ApplyBibtexFixesResult> {
  return postVersionedJson("/bibtex/fixes/apply", request, options);
}

export function validateBibtexForRegistration(
  request: ValidateRegistrationRequest,
  options?: BibtexRequestOptions,
): Promise<RegistrationValidationResult> {
  return postVersionedJson("/bibtex/registration/validate", request, options);
}

export function canonicalizeBibtexForStorage(
  request: ValidateRegistrationRequest,
  options?: BibtexRequestOptions,
): Promise<RegistrationValidationResult> {
  return postVersionedJson(
    "/bibtex/registration/canonicalize",
    request,
    options,
  );
}

export function exportBibtex(
  request: ExportBibtexRequest,
  options?: BibtexRequestOptions,
): Promise<BibtexExportResult> {
  return postVersionedJson("/bibtex/export", request, options);
}

export function listBibtexExportProfiles(
  options?: BibtexRequestOptions,
): Promise<BibtexExportProfilesResult> {
  return getVersionedJson("/bibtex/export/profiles", options);
}

async function getVersionedJson<T extends { schema_version: "1" }>(
  path: string,
  options?: BibtexRequestOptions,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "GET",
    headers: jsonHeaders(),
    signal: options?.signal,
  });
  return versionedResponse(response);
}

async function postVersionedJson<T extends { schema_version: "1" }>(
  path: string,
  body: object,
  options?: BibtexRequestOptions,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal: options?.signal,
  });
  return versionedResponse(response);
}

async function versionedResponse<T extends { schema_version: "1" }>(
  response: Response,
): Promise<T> {
  const payload = await readResponsePayload(response);

  if (!response.ok) {
    throw apiError(payload, response.status);
  }
  if (!isRecord(payload) || payload.schema_version !== "1") {
    throw new BibtexApiError("Unsupported bibmgr response schema.", {
      code: "unsupported_schema",
      status: response.status,
    });
  }

  return payload as T;
}

function jsonHeaders(): Headers {
  return new Headers({ "Content-Type": "application/json" });
}

async function readResponsePayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  return text ? { message: text } : {};
}

function apiError(payload: unknown, status: number): BibtexApiError {
  const record = isRecord(payload) ? payload : undefined;
  const error = isRecord(record?.error) ? record.error : undefined;
  const message =
    stringValue(error?.message) ??
    stringValue(record?.detail) ??
    stringValue(record?.message) ??
    `BibTeX request failed with status ${status}.`;

  return new BibtexApiError(message, {
    code: stringValue(error?.code) ?? "request_failed",
    status,
    details: isRecord(error?.details) ? error.details : undefined,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export type { BibmgrErrorResponse };
