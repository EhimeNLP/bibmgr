// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ThemeSwitcher from "../src/components/ThemeSwitcher.vue";
import { THEME_STORAGE_KEY } from "../src/theme";

type ThemeListener = (event: MediaQueryListEvent) => void;

let prefersDark = false;
let themeListener: ThemeListener | null = null;

beforeEach(() => {
  const storedThemes = new Map<string, string>();
  const storage = {
    getItem: (key: string) => storedThemes.get(key) ?? null,
    setItem: (key: string, value: string) => storedThemes.set(key, value),
    removeItem: (key: string) => storedThemes.delete(key),
    clear: () => storedThemes.clear(),
  };
  vi.stubGlobal("localStorage", storage);
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: storage,
  });

  prefersDark = false;
  themeListener = null;
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.themePreference;

  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation(
      (): Partial<MediaQueryList> => ({
        get matches() {
          return prefersDark;
        },
        addEventListener: (_event: string, listener: EventListenerOrEventListenerObject) => {
          themeListener = listener as ThemeListener;
        },
        removeEventListener: vi.fn(),
      }),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ThemeSwitcher", () => {
  it("defaults to system and follows changes to the system appearance", async () => {
    const wrapper = mount(ThemeSwitcher);

    expect(
      wrapper.get<HTMLInputElement>('input[value="system"]').element.checked,
    ).toBe(true);
    expect(document.documentElement.dataset).toMatchObject({
      theme: "light",
      themePreference: "system",
    });

    prefersDark = true;
    themeListener?.({ matches: true } as MediaQueryListEvent);
    await wrapper.vm.$nextTick();

    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("persists an explicit theme and ignores later system changes", async () => {
    const wrapper = mount(ThemeSwitcher);

    await wrapper.get('input[value="dark"]').setValue(true);

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset).toMatchObject({
      theme: "dark",
      themePreference: "dark",
    });

    themeListener?.({ matches: false } as MediaQueryListEvent);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("restores a saved preference", async () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    prefersDark = true;

    const wrapper = mount(ThemeSwitcher);
    await wrapper.vm.$nextTick();

    expect(
      wrapper.get<HTMLInputElement>('input[value="light"]').element.checked,
    ).toBe(true);
    expect(document.documentElement.dataset).toMatchObject({
      theme: "light",
      themePreference: "light",
    });
  });
});
