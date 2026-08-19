export const THEME_STORAGE_KEY = "bibmgr-theme";
export const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = Exclude<ThemePreference, "system">;

export function isThemePreference(value: string | null): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function readThemePreference(): ThemePreference {
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(storedTheme) ? storedTheme : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }

  return preference;
}

export function applyTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
) {
  const resolvedTheme = resolveTheme(preference, systemPrefersDark);
  const root = document.documentElement;

  root.dataset.theme = resolvedTheme;
  root.dataset.themePreference = preference;

  const themeColor = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  themeColor?.setAttribute(
    "content",
    resolvedTheme === "dark" ? "#0b0b0c" : "#f5f5f7",
  );
}

export function storeThemePreference(preference: ThemePreference) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Theme selection still works for this session when storage is unavailable.
  }
}
