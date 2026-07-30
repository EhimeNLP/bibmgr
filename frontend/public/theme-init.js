(() => {
  const storageKey = "bibmgr-theme";
  const storedTheme = (() => {
    try {
      return localStorage.getItem(storageKey);
    } catch {
      return null;
    }
  })();
  const preference = ["light", "dark", "system"].includes(storedTheme)
    ? storedTheme
    : "system";
  const resolvedTheme =
    preference === "system"
      ? matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : preference;

  document.documentElement.dataset.theme = resolvedTheme;
  document.documentElement.dataset.themePreference = preference;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute(
      "content",
      resolvedTheme === "dark" ? "#0b0b0c" : "#f5f5f7",
    );
})();
