import type {
  AuthenticationSession,
  EmailLoginStartResult,
} from "../types/auth";

const API_BASE_URL = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api"
).replace(/\/$/, "");

let currentCsrfToken: string | undefined;
export const AUTHENTICATION_REQUIRED_EVENT =
  "bibmgr:authentication-required";

export async function getAuthenticationSession(): Promise<AuthenticationSession> {
  const response = await fetch(`${API_BASE_URL}/auth/session`, {
    method: "GET",
    credentials: "include",
  });
  const payload = await readJson(response);
  if (!response.ok || !isAuthenticationSession(payload)) {
    throw authError(payload, response.status);
  }
  rememberSession(payload);
  return payload;
}

export async function startEmailLogin(
  email: string,
): Promise<EmailLoginStartResult> {
  const response = await fetch(`${API_BASE_URL}/auth/email/start`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  const payload = await readJson(response);
  if (!response.ok || !isRecord(payload)) {
    throw authError(payload, response.status);
  }
  return payload as EmailLoginStartResult;
}

export async function verifyEmailLogin(
  email: string,
  code: string,
): Promise<AuthenticationSession> {
  const response = await fetch(`${API_BASE_URL}/auth/email/verify`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code }),
  });
  const payload = await readJson(response);
  if (!response.ok || !isAuthenticationSession(payload)) {
    throw authError(payload, response.status);
  }
  rememberSession(payload);
  return payload;
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    credentials: "include",
    headers: authenticatedWriteHeaders(),
  });
  if (!response.ok) {
    handleAuthenticationFailure(response.status);
    throw authError(await readJson(response), response.status);
  }
  currentCsrfToken = undefined;
}

export function authenticatedWriteHeaders(
  options: { json?: boolean } = {},
): Headers {
  const headers = new Headers();
  if (options.json) {
    headers.set("Content-Type", "application/json");
  }
  if (currentCsrfToken) {
    headers.set("X-CSRF-Token", currentCsrfToken);
  }
  return headers;
}

export function handleAuthenticationFailure(status: number): void {
  if (status !== 401) return;
  currentCsrfToken = undefined;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTHENTICATION_REQUIRED_EVENT));
  }
}

export function clearRememberedAuthentication(): void {
  currentCsrfToken = undefined;
}

function rememberSession(session: AuthenticationSession) {
  currentCsrfToken = session.authenticated
    ? session.csrfToken
    : undefined;
}

async function readJson(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return undefined;
  return response.json();
}

function authError(payload: unknown, status: number): Error {
  const record = isRecord(payload) ? payload : undefined;
  const error = isRecord(record?.error) ? record.error : undefined;
  const message =
    stringValue(error?.message) ??
    stringValue(record?.message) ??
    `Authentication request failed with status ${status}.`;
  return new Error(message);
}

function isAuthenticationSession(
  value: unknown,
): value is AuthenticationSession {
  if (!isRecord(value) || value.schema_version !== "1") return false;
  if (typeof value.authenticated !== "boolean") return false;
  if (!value.authenticated) return true;
  const user = isRecord(value.user) ? value.user : undefined;
  return Boolean(
    user &&
      stringValue(user.id) &&
      stringValue(user.email) &&
      stringValue(value.csrfToken),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
