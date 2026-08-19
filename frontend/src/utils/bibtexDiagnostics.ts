import type { TextRange } from "../types/bibtex";

/** A half-open range expressed as JavaScript UTF-16 string indices. */
export type Utf16TextRange = {
  start: number;
  end: number;
};

/**
 * Convert a Rust UTF-8 byte offset to the corresponding JavaScript UTF-16
 * string index. Invalid offsets inside a code point are clamped to its start.
 */
export function utf8ByteOffsetToUtf16Index(
  source: string,
  byteOffset: number,
): number {
  const target = Math.max(0, Math.floor(Number.isFinite(byteOffset) ? byteOffset : 0));
  let utf8Offset = 0;
  let utf16Index = 0;

  for (const character of source) {
    if (utf8Offset >= target) break;

    const byteLength = utf8CodePointLength(character.codePointAt(0) ?? 0);
    if (utf8Offset + byteLength > target) break;

    utf8Offset += byteLength;
    utf16Index += character.length;
  }

  return utf16Index;
}

/** Convert a half-open Rust UTF-8 byte range to JavaScript UTF-16 indices. */
export function utf8ByteRangeToUtf16Range(
  source: string,
  range: TextRange,
): Utf16TextRange {
  const start = utf8ByteOffsetToUtf16Index(source, range.start);
  const end = utf8ByteOffsetToUtf16Index(source, range.end);
  return {
    start: Math.min(start, end),
    end: Math.max(start, end),
  };
}

function utf8CodePointLength(codePoint: number): number {
  if (codePoint <= 0x7f) return 1;
  if (codePoint <= 0x7ff) return 2;
  if (codePoint <= 0xffff) return 3;
  return 4;
}
