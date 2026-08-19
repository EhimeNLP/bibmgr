import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authenticatedWriteHeaders,
  getAuthenticationSession,
  logout,
  startEmailLogin,
  verifyEmailLogin,
} from "../src/api/auth";

const authenticatedSession = {
  schema_version: "1" as const,
  authenticated: true,
  user: {
    id: "7ca9f85d-b16f-470b-a6a8-ab6d8582eb36",
    email: "member@example.test",
  },
  csrfToken: "csrf-token",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("authentication API", () => {
  it("requests and verifies an email login code", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          schema_version: "1",
          accepted: true,
          message: "A code has been sent.",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(authenticatedSession));
    vi.stubGlobal("fetch", fetchMock);

    await startEmailLogin("member@example.test");
    await expect(
      verifyEmailLogin("member@example.test", "12345678"),
    ).resolves.toEqual(authenticatedSession);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/auth/email/start");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/auth/email/verify");
    const [, verifyInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(verifyInit.credentials).toBe("include");
    expect(JSON.parse(String(verifyInit.body))).toEqual({
      email: "member@example.test",
      code: "12345678",
    });
    expect(authenticatedWriteHeaders({ json: true }).get("X-CSRF-Token")).toBe(
      "csrf-token",
    );
  });

  it("restores a session and sends CSRF protection on logout", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(authenticatedSession))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await getAuthenticationSession();
    await logout();

    const [, logoutInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(logoutInit.credentials).toBe("include");
    expect(new Headers(logoutInit.headers).get("X-CSRF-Token")).toBe(
      "csrf-token",
    );
    expect(authenticatedWriteHeaders().has("X-CSRF-Token")).toBe(false);
  });

  it("does not treat a malformed response as a session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ authenticated: true })),
    );

    await expect(getAuthenticationSession()).rejects.toThrow(
      "Authentication request failed",
    );
  });
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
