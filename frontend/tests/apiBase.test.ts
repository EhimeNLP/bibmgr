import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "../src/api/base";

describe("API base URL", () => {
  it("keeps the root deployment default", () => {
    expect(resolveApiBaseUrl("/")).toBe("/api");
  });

  it("inherits a configured application subpath", () => {
    expect(resolveApiBaseUrl("/bibmgr/")).toBe("/bibmgr/api");
  });

  it("prefers and normalizes an explicit API override", () => {
    expect(
      resolveApiBaseUrl("/bibmgr/", "https://api.example.test/v1/"),
    ).toBe("https://api.example.test/v1");
  });
});
