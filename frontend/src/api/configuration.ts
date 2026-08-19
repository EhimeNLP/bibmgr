import {
  authenticatedWriteHeaders,
  handleAuthenticationFailure,
} from "./auth";
import { API_BASE_URL } from "./base";
import { BibtexApiError } from "./bibtex";
import type {
  ApplicationConfiguration,
  ConfigurationDeleteResult,
  ConfigurationEntry,
  ConfigurationHistoryPage,
  ConfigurationKind,
  ConfigurationUpdateResult,
  ExportProfileData,
  ExportProfilePreviewRequest,
  ExportProfilePreviewResult,
  VenueData,
} from "../types/configuration";

export async function getApplicationConfiguration(): Promise<ApplicationConfiguration> {
  const response = await fetch(`${API_BASE_URL}/settings/configuration`, {
    method: "GET",
    credentials: "include",
  });
  return configurationResponse<ApplicationConfiguration>(response);
}

export async function getConfigurationHistory(
  kind: ConfigurationKind,
  {
    limit = 50,
    offset = 0,
  }: { limit?: number; offset?: number } = {},
): Promise<ConfigurationHistoryPage> {
  const query = new URLSearchParams({
    kind,
    limit: String(limit),
    offset: String(offset),
  });
  const response = await fetch(
    `${API_BASE_URL}/settings/configuration-history?${query}`,
    {
      method: "GET",
      credentials: "include",
    },
  );
  return configurationResponse<ConfigurationHistoryPage>(response);
}

export async function previewExportProfile(
  request: ExportProfilePreviewRequest,
  signal?: AbortSignal,
): Promise<ExportProfilePreviewResult> {
  const response = await fetch(
    `${API_BASE_URL}/settings/export-profiles/preview`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    },
  );
  return configurationResponse<ExportProfilePreviewResult>(response);
}

export async function updateExportProfile(
  entry: Pick<ConfigurationEntry<ExportProfileData>, "key" | "revision">,
  data: ExportProfileData,
): Promise<ConfigurationUpdateResult<ExportProfileData>> {
  return updateConfiguration(
    `/settings/export-profiles/${encodeURIComponent(entry.key)}`,
    data,
    entry.revision,
  );
}

export async function updateVenue(
  entry: Pick<ConfigurationEntry<VenueData>, "key" | "revision">,
  data: VenueData,
): Promise<ConfigurationUpdateResult<VenueData>> {
  return updateConfiguration(
    `/settings/venues/${encodeURIComponent(entry.key)}`,
    data,
    entry.revision,
  );
}

export async function deleteExportProfile(
  entry: Pick<ConfigurationEntry<ExportProfileData>, "key" | "revision">,
): Promise<ConfigurationDeleteResult> {
  return deleteConfiguration(
    `/settings/export-profiles/${encodeURIComponent(entry.key)}`,
    entry.revision,
  );
}

export async function deleteVenue(
  entry: Pick<ConfigurationEntry<VenueData>, "key" | "revision">,
): Promise<ConfigurationDeleteResult> {
  return deleteConfiguration(
    `/settings/venues/${encodeURIComponent(entry.key)}`,
    entry.revision,
  );
}

async function updateConfiguration<T extends object>(
  path: string,
  data: T,
  expectedRevision: number,
): Promise<ConfigurationUpdateResult<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PUT",
    credentials: "include",
    headers: authenticatedWriteHeaders({ json: true }),
    body: JSON.stringify({
      data,
      expected_revision: expectedRevision,
    }),
  });
  return configurationResponse<ConfigurationUpdateResult<T>>(response);
}

async function deleteConfiguration(
  path: string,
  expectedRevision: number,
): Promise<ConfigurationDeleteResult> {
  const query = new URLSearchParams({
    expected_revision: String(expectedRevision),
  });
  const response = await fetch(`${API_BASE_URL}${path}?${query}`, {
    method: "DELETE",
    credentials: "include",
    headers: authenticatedWriteHeaders(),
  });
  return configurationResponse<ConfigurationDeleteResult>(response);
}

async function configurationResponse<T>(response: Response): Promise<T> {
  const payload = await readPayload(response);
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    const error = isRecord(payload) && isRecord(payload.error)
      ? payload.error
      : undefined;
    throw new BibtexApiError(
      stringValue(error?.message) ?? "Configuration request failed.",
      {
        code: stringValue(error?.code) ?? "configuration_request_failed",
        status: response.status,
        details: isRecord(error?.details) ? error.details : undefined,
      },
    );
  }
  if (!isRecord(payload) || payload.schema_version !== "1") {
    throw new BibtexApiError("Invalid configuration response.", {
      code: "invalid_configuration_response",
      status: response.status,
    });
  }
  return payload as T;
}

async function readPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("application/json")
    ? response.json()
    : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
