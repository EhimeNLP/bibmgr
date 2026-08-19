export function normalizeDisplayWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function bibtexTitleForDisplay(value: string): string {
  let output = "";
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    const next = value[index + 1];
    if (character === "\\" && (next === "{" || next === "}")) {
      output += next;
      index += 1;
      continue;
    }
    if (character !== "{" && character !== "}") {
      output += character;
    }
  }
  return normalizeDisplayWhitespace(output);
}
