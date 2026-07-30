import { describe, expect, it } from "vitest";
import {
  createJsonDiff,
  createTextDiff,
} from "../src/utils/textDiff";

describe("createTextDiff", () => {
  it("tracks old and new line numbers for replacements", () => {
    const diff = createTextDiff("alpha\nold\nomega\n", "alpha\nnew\nomega\n");

    expect(diff.additions).toBe(1);
    expect(diff.deletions).toBe(1);
    expect(diff.rows).toEqual([
      {
        kind: "context",
        oldLine: 1,
        newLine: 1,
        marker: " ",
        text: "alpha",
      },
      {
        kind: "deletion",
        oldLine: 2,
        newLine: null,
        marker: "-",
        text: "old",
      },
      {
        kind: "addition",
        oldLine: null,
        newLine: 2,
        marker: "+",
        text: "new",
      },
      {
        kind: "context",
        oldLine: 3,
        newLine: 3,
        marker: " ",
        text: "omega",
      },
    ]);
  });

  it("renders creation and deletion as entirely added or removed", () => {
    const creation = createTextDiff("", "first\nsecond\n");
    const deletion = createTextDiff("first\nsecond\n", "");

    expect(creation.rows.map((row) => row.kind)).toEqual([
      "addition",
      "addition",
    ]);
    expect(creation.additions).toBe(2);
    expect(deletion.rows.map((row) => row.kind)).toEqual([
      "deletion",
      "deletion",
    ]);
    expect(deletion.deletions).toBe(2);
  });
});

describe("createJsonDiff", () => {
  it("does not treat object property order as a change", () => {
    const diff = createJsonDiff(
      { profile: "laboratory", description: "Laboratory output." },
      { description: "Laboratory output.", profile: "laboratory" },
    );

    expect(diff.additions).toBe(0);
    expect(diff.deletions).toBe(0);
    expect(diff.rows.every((row) => row.kind === "context")).toBe(true);
  });

  it.each([
    {
      label: "export profile",
      before: {
        profile: "laboratory",
        display_name: "Laboratory",
        description: "Original profile description.",
      },
      after: {
        description: "Updated profile description.",
        display_name: "Laboratory",
        profile: "laboratory",
      },
      removed: '"description": "Original profile description."',
      added: '"description": "Updated profile description."',
    },
    {
      label: "venue mapping",
      before: {
        id: "acl-annual-meeting",
        full_name:
          "Annual Meeting of the Association for Computational Linguistics",
        short_name: "ACL",
        aliases: ["Proceedings of ACL"],
        kind: "conference",
      },
      after: {
        kind: "conference",
        aliases: ["Proceedings of ACL"],
        short_name: "ACL Annual",
        full_name:
          "Annual Meeting of the Association for Computational Linguistics",
        id: "acl-annual-meeting",
      },
      removed: '"short_name": "ACL"',
      added: '"short_name": "ACL Annual"',
    },
  ])(
    "reports only the changed line for a $label",
    ({ before, after, removed, added }) => {
      const diff = createJsonDiff(before, after);
      const changedRows = diff.rows.filter(
        (row) => row.kind !== "context",
      );

      expect(diff.additions).toBe(1);
      expect(diff.deletions).toBe(1);
      expect(changedRows).toEqual([
        expect.objectContaining({
          kind: "deletion",
          text: expect.stringContaining(removed),
        }),
        expect.objectContaining({
          kind: "addition",
          text: expect.stringContaining(added),
        }),
      ]);
    },
  );

  it("renders JSON creation and deletion as entirely added or removed", () => {
    const value = { profile: "custom", display_name: "Custom" };
    const creation = createJsonDiff(null, value);
    const deletion = createJsonDiff(value, null);

    expect(creation.additions).toBe(4);
    expect(creation.deletions).toBe(0);
    expect(creation.rows.every((row) => row.kind === "addition")).toBe(true);
    expect(deletion.additions).toBe(0);
    expect(deletion.deletions).toBe(4);
    expect(deletion.rows.every((row) => row.kind === "deletion")).toBe(true);
  });
});
