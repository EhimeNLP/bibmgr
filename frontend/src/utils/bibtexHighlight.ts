export type BibtexTokenKind =
  | "plain"
  | "entry"
  | "key"
  | "field"
  | "value"
  | "number"
  | "punctuation"
  | "comment";

export type BibtexToken = {
  kind: BibtexTokenKind;
  value: string;
};

export const MAX_BIBTEX_HIGHLIGHT_LENGTH = 200_000;

const SPECIAL_ENTRY_TYPES = new Set(["comment", "preamble", "string"]);

export function tokenizeBibtexForHighlight(source: string): BibtexToken[] {
  return source.length > MAX_BIBTEX_HIGHLIGHT_LENGTH
    ? [{ kind: "plain", value: source }]
    : tokenizeBibtex(source);
}

export function tokenizeBibtex(source: string): BibtexToken[] {
  const tokens: BibtexToken[] = [];
  let index = 0;
  let expectingEntryOpen = false;
  let expectingCitationKey = false;
  let awaitingEquals = false;
  let expectingValue = false;

  const push = (kind: BibtexTokenKind, value: string) => {
    if (!value) return;
    const previous = tokens.at(-1);
    if (previous?.kind === kind) {
      previous.value += value;
    } else {
      tokens.push({ kind, value });
    }
  };

  while (index < source.length) {
    const character = source[index];

    if (character === "%" && source[index - 1] !== "\\") {
      const end = lineEnd(source, index);
      push("comment", source.slice(index, end));
      index = end;
      continue;
    }

    if (character === "@" && isIdentifierStart(source[index + 1])) {
      const end = identifierEnd(source, index + 1);
      push("entry", source.slice(index, end));
      index = end;
      expectingEntryOpen = true;
      expectingCitationKey = false;
      awaitingEquals = false;
      expectingValue = false;
      continue;
    }

    if (expectingEntryOpen) {
      if (isWhitespace(character)) {
        push("plain", character);
        index += 1;
        continue;
      }

      if (character === "{" || character === "(") {
        push("punctuation", character);
        index += 1;
        expectingEntryOpen = false;
        expectingCitationKey = true;
        continue;
      }

      expectingEntryOpen = false;
    }

    if (expectingCitationKey) {
      if (isWhitespace(character)) {
        push("plain", character);
        index += 1;
        continue;
      }

      const commaIndex = source.indexOf(",", index);
      const newlineIndex = nextLineBreak(source, index);
      const end = minimumPositive(commaIndex, newlineIndex, source.length);
      push("key", source.slice(index, end));
      index = end;
      expectingCitationKey = false;
      continue;
    }

    if (expectingValue) {
      if (isWhitespace(character)) {
        push("plain", character);
        index += 1;
        continue;
      }

      if (character === "{") {
        const end = balancedGroupEnd(source, index, "{", "}");
        push("value", source.slice(index, end));
        index = end;
        expectingValue = false;
        continue;
      }

      if (character === '"') {
        const end = quotedValueEnd(source, index);
        push("value", source.slice(index, end));
        index = end;
        expectingValue = false;
        continue;
      }

      const end = unbracedValueEnd(source, index);
      const value = source.slice(index, end);
      push(/^\d+(?:\.\d+)?$/.test(value.trim()) ? "number" : "value", value);
      index = Math.max(end, index + 1);
      expectingValue = false;
      continue;
    }

    if (isIdentifierStart(character)) {
      const end = identifierEnd(source, index);
      const word = source.slice(index, end);
      const nextNonWhitespace = skipWhitespace(source, end);
      if (source[nextNonWhitespace] === "=") {
        push("field", word);
        awaitingEquals = true;
      } else if (/^\d+(?:\.\d+)?$/.test(word)) {
        push("number", word);
      } else {
        push("plain", word);
      }
      index = end;
      continue;
    }

    if (awaitingEquals && character === "=") {
      push("punctuation", character);
      awaitingEquals = false;
      expectingValue = true;
      index += 1;
      continue;
    }

    if (awaitingEquals && !isWhitespace(character)) {
      awaitingEquals = false;
    }

    if ("{}(),=".includes(character)) {
      push("punctuation", character);
    } else if (/\d/.test(character)) {
      const end = numberEnd(source, index);
      push("number", source.slice(index, end));
      index = end;
      continue;
    } else {
      push("plain", character);
    }
    index += 1;
  }

  return tokens;
}

export function countBibliographicEntries(source: string): number {
  return extractBibliographicEntries(source).length;
}

export function extractBibliographicEntries(source: string): string[] {
  const entries: string[] = [];
  let index = 0;

  while (index < source.length) {
    if (source[index] === "%" && source[index - 1] !== "\\") {
      index = lineEnd(source, index);
      continue;
    }

    if (source[index] !== "@" || !isIdentifierStart(source[index + 1])) {
      index += 1;
      continue;
    }

    const typeEnd = identifierEnd(source, index + 1);
    const entryType = source.slice(index + 1, typeEnd).toLowerCase();
    const openIndex = skipWhitespace(source, typeEnd);
    const open = source[openIndex];
    if (open !== "{" && open !== "(") {
      index = typeEnd;
      continue;
    }

    const end = bibtexEntryEnd(source, openIndex, open, open === "{" ? "}" : ")");
    if (end === undefined) {
      index = typeEnd;
      continue;
    }

    if (!SPECIAL_ENTRY_TYPES.has(entryType)) {
      entries.push(source.slice(index, end));
    }
    index = end;
  }

  return entries;
}

function isIdentifierStart(value: string | undefined): boolean {
  return Boolean(value && /[A-Za-z0-9_:-]/.test(value));
}

function isIdentifierPart(value: string | undefined): boolean {
  return Boolean(value && /[A-Za-z0-9_.:/-]/.test(value));
}

function identifierEnd(source: string, start: number): number {
  let index = start;
  while (isIdentifierPart(source[index])) index += 1;
  return index;
}

function numberEnd(source: string, start: number): number {
  let index = start;
  while (source[index] && /[\d.]/.test(source[index])) index += 1;
  return index;
}

function lineEnd(source: string, start: number): number {
  const newline = source.indexOf("\n", start);
  return newline === -1 ? source.length : newline;
}

function nextLineBreak(source: string, start: number): number {
  const newline = source.indexOf("\n", start);
  const carriageReturn = source.indexOf("\r", start);
  return minimumPositive(newline, carriageReturn, source.length);
}

function minimumPositive(...values: number[]): number {
  return Math.min(...values.filter((value) => value >= 0));
}

function isWhitespace(value: string | undefined): boolean {
  return Boolean(value && /\s/.test(value));
}

function skipWhitespace(source: string, start: number): number {
  let index = start;
  while (isWhitespace(source[index])) index += 1;
  return index;
}

function balancedGroupEnd(
  source: string,
  start: number,
  open: string,
  close: string,
): number {
  let depth = 0;
  let escaped = false;
  for (let index = start; index < source.length; index += 1) {
    const character = source[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
      continue;
    }
    if (character === open) depth += 1;
    if (character === close) {
      depth -= 1;
      if (depth === 0) return index + 1;
    }
  }
  return source.length;
}

function quotedValueEnd(source: string, start: number): number {
  let escaped = false;
  for (let index = start + 1; index < source.length; index += 1) {
    const character = source[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
      continue;
    }
    if (character === '"') return index + 1;
  }
  return source.length;
}

function unbracedValueEnd(source: string, start: number): number {
  let index = start;
  while (
    index < source.length &&
    source[index] !== "," &&
    source[index] !== "\n" &&
    source[index] !== "\r" &&
    source[index] !== "}"
  ) {
    index += 1;
  }
  return index;
}

function bibtexEntryEnd(
  source: string,
  start: number,
  open: string,
  close: string,
): number | undefined {
  let depth = 0;
  let escaped = false;
  let inQuote = false;
  let inComment = false;

  for (let index = start; index < source.length; index += 1) {
    const character = source[index];

    if (inComment) {
      if (character === "\n" || character === "\r") inComment = false;
      continue;
    }

    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
      continue;
    }
    if (character === "%" && !inQuote) {
      inComment = true;
      continue;
    }
    if (character === '"') {
      inQuote = !inQuote;
      continue;
    }
    if (inQuote) continue;

    if (character === open) depth += 1;
    if (character === close) {
      depth -= 1;
      if (depth === 0) return index + 1;
    }
  }

  return undefined;
}
