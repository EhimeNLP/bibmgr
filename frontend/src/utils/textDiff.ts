import {
  diffJson,
  diffLines,
  type Change,
} from "diff";

export type DiffLineKind = "context" | "addition" | "deletion";

export type DiffLine = {
  kind: DiffLineKind;
  oldLine: number | null;
  newLine: number | null;
  marker: " " | "+" | "-";
  text: string;
};

export type TextDiff = {
  rows: DiffLine[];
  additions: number;
  deletions: number;
};

export function createTextDiff(before: string, after: string): TextDiff {
  return createDiffRows(diffLines(before, after));
}

export function createJsonDiff(
  before: string | object | null,
  after: string | object | null,
): TextDiff {
  return createDiffRows(diffJson(before ?? "", after ?? ""));
}

function createDiffRows(changes: Change[]): TextDiff {
  let oldLine = 1;
  let newLine = 1;
  let additions = 0;
  let deletions = 0;
  const rows: DiffLine[] = [];

  for (const change of changes) {
    for (const text of splitChangedLines(change.value)) {
      if (change.added) {
        rows.push({
          kind: "addition",
          oldLine: null,
          newLine,
          marker: "+",
          text,
        });
        newLine += 1;
        additions += 1;
      } else if (change.removed) {
        rows.push({
          kind: "deletion",
          oldLine,
          newLine: null,
          marker: "-",
          text,
        });
        oldLine += 1;
        deletions += 1;
      } else {
        rows.push({
          kind: "context",
          oldLine,
          newLine,
          marker: " ",
          text,
        });
        oldLine += 1;
        newLine += 1;
      }
    }
  }

  return { rows, additions, deletions };
}

function splitChangedLines(value: string): string[] {
  if (!value) return [];
  const lines = value.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}
