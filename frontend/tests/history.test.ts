import { afterEach, describe, expect, it, vi } from "vitest";
import { verifyEmailLogin } from "../src/api/auth";
import {
  getReferenceHistory,
  listReferenceHistory,
  pageReferenceHistory,
  revertReference,
} from "../src/api/history";

const referenceId = "4546d52e-39dc-4031-9df5-07c06f816a48";
const session = {
  schema_version: "1",
  authenticated: true,
  user: {
    id: "7ca9f85d-b16f-470b-a6a8-ab6d8582eb36",
    email: "member@example.test",
  },
  csrfToken: "history-csrf-token",
};
const summary = {
  referenceId,
  headRevision: 3,
  exists: false,
  title: "Deleted paper",
  latestAction: "delete",
  updatedAt: "2026-07-27T12:00:00Z",
};
const history = {
  referenceId,
  headRevision: 3,
  exists: false,
  revisions: [
    {
      revision: 3,
      action: "delete",
      actor: session.user,
      occurredAt: "2026-07-27T12:00:00Z",
      title: "Deleted paper",
      sourceRevision: `sha256:${"a".repeat(64)}`,
      restorable: false,
    },
    {
      revision: 1,
      action: "create",
      actor: session.user,
      occurredAt: "2026-07-27T10:00:00Z",
      title: "Original paper",
      sourceRevision: `sha256:${"b".repeat(64)}`,
      restorable: true,
    },
  ],
};
const restoredReference = {
  id: referenceId,
  title: "Original paper",
  authors: ["Lab Member"],
  bibtex: "@article{original}",
  sourceRevision: `sha256:${"b".repeat(64)}`,
  citationContexts: [],
  createdAt: "2026-07-27T10:00:00Z",
  updatedAt: "2026-07-27T13:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("reference history API", () => {
  it("loads deleted history and sends a revision-checked restore", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(session))
      .mockResolvedValueOnce(jsonResponse([summary]))
      .mockResolvedValueOnce(jsonResponse(history))
      .mockResolvedValueOnce(jsonResponse(restoredReference));
    vi.stubGlobal("fetch", fetchMock);

    await verifyEmailLogin(
      "member@example.test",
      "12345678",
    );
    await expect(listReferenceHistory()).resolves.toEqual([summary]);
    await expect(getReferenceHistory(referenceId)).resolves.toEqual(history);
    await expect(revertReference(referenceId, 1, 3)).resolves.toMatchObject({
      id: referenceId,
      title: "Original paper",
    });

    const [, restoreInit] = fetchMock.mock.calls[3] as [
      string,
      RequestInit,
    ];
    expect(restoreInit.method).toBe("POST");
    expect(new Headers(restoreInit.headers).get("X-CSRF-Token")).toBe(
      "history-csrf-token",
    );
    expect(JSON.parse(String(restoreInit.body))).toEqual({
      target_revision: 1,
      expected_head_revision: 3,
    });
  });

  it("loads a paginated history index", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          items: [{ ...summary, latestAction: "context" }],
          total: 27,
          limit: 25,
          offset: 25,
        }),
      ),
    );

    await expect(
      pageReferenceHistory({ limit: 25, offset: 25 }),
    ).resolves.toEqual({
      items: [{ ...summary, latestAction: "context" }],
      total: 27,
      limit: 25,
      offset: 25,
    });
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
