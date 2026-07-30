import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";

test("authenticated access, CRUD, restore, and accessibility", async ({
  page,
  request,
}) => {
  const runId = Date.now().toString(36);
  const email = `e2e-${runId}@ai.cs.ehime-u.ac.jp`;
  const referenceTitle = `End-to-End Reference ${runId}`;
  const editedReferenceTitle = `Edited ${referenceTitle}`;

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Log in to access BibMgR" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "References", exact: true }),
  ).toHaveCount(0);
  await assertNoSeriousAccessibilityViolations(page);

  await page
    .getByRole("button", { name: "Log in", exact: true })
    .click();
  await page.getByLabel("Laboratory email").fill(email);
  const requestedAt = Date.now();
  await page.getByRole("button", { name: "Send login code" }).click();
  const code = await latestMailpitCode(request, email, requestedAt);
  await page.getByLabel("8-digit login code").fill(code);
  const loginDialog = page.getByRole("dialog", { name: "Log in to BibMgR" });
  await page
    .getByRole("dialog", { name: "Log in to BibMgR" })
    .getByRole("button", { name: "Log in", exact: true })
    .click();
  await expect(loginDialog).toHaveCount(0);
  await expect(page.getByText(email)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "References", exact: true }),
  ).toBeVisible();

  await verifyApplicationSettings(page, runId, email);

  await page.getByRole("button", { name: "Add reference" }).click();
  await page.getByLabel("BibTeX entry").fill(
    [
      `@article{researcher-2026-e2e-${runId},`,
      "  author = {Researcher, Example},",
      `  title = {${referenceTitle}},`,
      "  journal = {Transactions of the Association for Computational Linguistics},",
      "  year = {2026},",
      `  doi = {10.9999/bibmgr-e2e-${runId}},`,
      `  url = {https://example.org/bibmgr-e2e-${runId}},`,
      "}",
      "",
    ].join("\n"),
  );
  await registerAndWaitForCompletion(page);
  await page.getByRole("button", { name: "Close add references" }).click();

  await page
    .getByRole("searchbox", { name: "Search references" })
    .fill(referenceTitle);
  await page.getByRole("button", { name: "Search references" }).click();
  await expect(
    page.getByRole("button", { name: new RegExp(referenceTitle) }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Reference actions" }).click();
  await page.getByRole("menuitem", { name: "Edit…" }).click();
  const editor = page.getByRole("textbox", {
    name: "Reference BibTeX entry",
  });
  await editor.fill(
    (await editor.inputValue()).replace(referenceTitle, editedReferenceTitle),
  );
  await saveAndWaitForDialogToClose(page);
  await expect(
    page
      .getByRole("region", { name: "Reference details" })
      .getByRole("heading", {
        name: editedReferenceTitle,
        level: 2,
      }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Reference actions" }).click();
  await page.getByRole("menuitem", { name: "Delete…" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: editedReferenceTitle }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Reference history" }).click();
  await page
    .getByRole("button", { name: new RegExp(editedReferenceTitle) })
    .click();
  const deletedRevision = page
    .locator(".history-list > li")
    .filter({ hasText: "Deleted" })
    .first();
  await deletedRevision.getByText("View BibTeX changes").click();
  await expect(
    deletedRevision.locator(".unified-diff .is-deletion").first(),
  ).toBeVisible();
  await expectCompactDiffGutter(
    deletedRevision.locator(".unified-diff"),
  );
  const restore = page.getByRole("button", { name: "Restore" }).last();
  await restore.click();
  await page.getByRole("button", { name: "Confirm restore" }).click();
  await expect(page.getByText(/was restored as a new revision/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Download .bib", exact: true }),
  ).toBeEnabled();
  await assertNoSeriousAccessibilityViolations(page);

  await page.getByRole("button", { name: "Close history" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  const signOutDialog = page.getByRole("alertdialog", {
    name: "Sign out?",
  });
  await signOutDialog.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Log in to access BibMgR" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "References", exact: true }),
  ).toHaveCount(0);
});

async function verifyApplicationSettings(
  page: Page,
  runId: string,
  email: string,
) {
  const customProfileId = `e2e-profile-${runId}`;
  const overrideDescription =
    `E2E shared override ${runId} ` + "wide-content-".repeat(50);
  await page
    .getByRole("button", { name: "Application settings", exact: true })
    .click();
  const settings = page.getByRole("dialog", {
    name: "Application settings",
  });
  await expect(settings).toBeVisible();
  await expect(
    settings.getByRole("button", { name: "Save profile", exact: true }),
  ).toBeDisabled();

  await settings
    .getByRole("button", { name: "Add export profile", exact: true })
    .click();
  await settings.getByLabel("Profile ID lowercase kebab-case").fill(
    customProfileId,
  );
  await settings.getByRole("button", { name: "Add profile" }).click();
  await expect(
    settings.getByRole("button", {
      name: new RegExp(`${customProfileId}$`),
    }),
  ).toBeVisible();
  await expect(settings.getByText("Custom profile · Revision 1")).toBeVisible();
  await expect(
    settings.getByRole("button", { name: "Save profile", exact: true }),
  ).toBeDisabled();

  await settings.getByRole("button", { name: "Delete…", exact: true }).click();
  await expect(settings.getByText("Delete this profile?")).toBeVisible();
  const confirmDelete = settings.getByRole("button", {
    name: "Delete",
    exact: true,
  });
  await expect(confirmDelete).toBeInViewport();
  await expect
    .poll(async () => {
      const confirmation = await confirmDelete.boundingBox();
      const editor = await settings
        .getByRole("heading", { name: "Profile details", exact: true })
        .boundingBox();
      return Boolean(
        confirmation && editor && confirmation.y < editor.y,
      );
    })
    .toBe(true);
  await confirmDelete.click();
  await expect(
    settings.getByRole("button", {
      name: new RegExp(`${customProfileId}$`),
    }),
  ).toHaveCount(0);

  await settings
    .getByRole("button", { name: "Modern BibTeX modern", exact: true })
    .click();
  const liveProfilePreview = settings.getByTestId("export-profile-preview");
  await expect(liveProfilePreview).toBeVisible();
  const trailingComma = settings.getByLabel(
    "Trailing comma on the last field",
    { exact: true },
  );
  await trailingComma.uncheck();
  await expect
    .poll(async () =>
      /,\s*}\s*$/.test((await liveProfilePreview.textContent()) ?? ""),
    )
    .toBe(false);
  await trailingComma.check();
  await expect
    .poll(async () =>
      /,\s*}\s*$/.test((await liveProfilePreview.textContent()) ?? ""),
    )
    .toBe(true);
  await settings.locator("details.profile-advanced > summary").click();
  await expect(settings.getByTestId("export-profile-json")).toBeVisible();
  await expect(
    settings.getByLabel("Profile definition (JSON)"),
  ).toHaveCount(0);
  const profileDescription = settings.getByLabel("Description", {
    exact: true,
  });
  const originalDescription = await profileDescription.inputValue();
  await profileDescription.fill(overrideDescription);
  await settings
    .getByRole("button", { name: "Save profile", exact: true })
    .click();
  await expect(settings.getByText(/Shared override, revision \d+/)).toBeVisible();
  await expect(
    settings.getByRole("button", { name: "Save profile", exact: true }),
  ).toBeDisabled();

  await settings
    .getByRole("button", { name: "Restore Default…", exact: true })
    .click();
  await expect(
    settings.getByText("Restore the built-in profile?"),
  ).toBeVisible();
  const confirmRestore = settings.getByRole("button", {
    name: "Restore Default",
    exact: true,
  });
  await expect(confirmRestore).toBeInViewport();
  await confirmRestore.click();
  await expect
    .poll(async () => {
      return profileDescription.inputValue();
    })
    .toBe(originalDescription);
  await expect(settings.getByText("Built-in profile · Default")).toBeVisible();
  await expect(
    settings.getByRole("button", { name: "Restore Default…", exact: true }),
  ).toHaveCount(0);
  await expect(
    settings.getByRole("button", { name: "Save profile", exact: true }),
  ).toBeDisabled();

  await settings
    .getByRole("button", {
      name: "View export profile history",
      exact: true,
    })
    .click();
  await expect(
    settings.getByRole("heading", { name: "Export profile history" }),
  ).toBeVisible();
  const deletedProfileHistory = settings
    .locator(".settings-history__list > li")
    .filter({ hasText: customProfileId })
    .filter({ hasText: "Deleted" });
  await expect(deletedProfileHistory).toContainText("Deleted");
  await expect(deletedProfileHistory).toContainText(email);
  await deletedProfileHistory.locator("summary").click();
  await expect(
    deletedProfileHistory.locator(".unified-diff .is-deletion").first(),
  ).toBeVisible();
  await expect(deletedProfileHistory.locator(".unified-diff")).toContainText(
    customProfileId,
  );
  await expectCompactDiffGutter(
    deletedProfileHistory.locator(".unified-diff"),
  );
  const changedProfileHistory = settings
    .locator(".settings-history__list > li")
    .filter({ hasText: "modern" })
    .filter({ hasText: /Overrode default|Updated/ })
    .filter({ hasText: email })
    .first();
  await expect(changedProfileHistory).toBeVisible();
  await changedProfileHistory.locator("summary").click();
  const overrideDiff = changedProfileHistory.locator(".unified-diff");
  await expect(overrideDiff).toContainText(
    /(?:Built-in default|Revision \d+) → Revision \d+/,
  );
  await expect(overrideDiff.locator(".is-deletion")).toHaveCount(1);
  await expect(overrideDiff.locator(".is-addition")).toHaveCount(1);
  await expect(overrideDiff.locator(".is-deletion")).toContainText(
    originalDescription,
  );
  await expect(overrideDiff.locator(".is-addition")).toContainText(
    overrideDescription,
  );
  await expectCompactDiffGutter(overrideDiff);
  await expectDiffHighlightSpansScrollWidth(overrideDiff);
  await expect(
    settings
      .locator(".settings-history__list > li")
      .filter({ hasText: "modern" })
      .filter({ hasText: "Restored default" })
      .first(),
  ).toBeVisible();
  await assertNoSeriousAccessibilityViolations(page);
  await settings.getByRole("button", { name: "Done", exact: true }).click();
  await expect(
    settings.getByRole("heading", { name: "Export profile history" }),
  ).toHaveCount(0);

  await settings
    .getByRole("button", { name: "Close settings", exact: true })
    .click();
  await expect(settings).toHaveCount(0);
}

async function registerAndWaitForCompletion(page: Page) {
  const editor = page.getByRole("textbox", { name: "BibTeX entry" });
  const register = page.getByRole("button", {
    name: "Register BibTeX",
    exact: true,
  });

  await expect(register).toBeEnabled();
  await register.click();
  await expect(editor).toHaveValue("");
}

async function saveAndWaitForDialogToClose(page: Page) {
  const dialog = page.getByRole("dialog", { name: "Edit reference" });
  const save = dialog.getByRole("button", {
    name: "Save changes",
    exact: true,
  });

  await expect(save).toBeEnabled();
  await save.click();
  await expect(dialog).toHaveCount(0);
}

async function latestMailpitCode(
  request: APIRequestContext,
  recipient: string,
  requestedAt: number,
): Promise<string> {
  let code = "";
  await expect
    .poll(
      async () => {
        const listResponse = await request.get(
          "http://127.0.0.1:8025/api/v1/messages",
        );
        if (!listResponse.ok()) return "";
        const list = (await listResponse.json()) as {
          messages?: Array<{
            ID?: string;
            Created?: string;
            To?: Array<{ Address?: string }>;
          }>;
        };
        const message = list.messages?.find((candidate) =>
          candidate.To?.some((address) => address.Address === recipient) &&
          candidate.Created &&
          new Date(candidate.Created).getTime() >= requestedAt - 2_000,
        );
        if (!message?.ID) return "";
        const response = await request.get(
          `http://127.0.0.1:8025/api/v1/message/${message.ID}`,
        );
        if (!response.ok()) return "";
        const payload = (await response.json()) as { Text?: string };
        code = payload.Text?.match(/\b\d{8}\b/)?.[0] ?? "";
        return code;
      },
      { timeout: 15_000 },
    )
    .toMatch(/^\d{8}$/);
  return code;
}

async function assertNoSeriousAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter((violation) =>
      ["critical", "serious"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
}

async function expectCompactDiffGutter(diff: Locator) {
  const cells = diff.locator("tbody tr").first().locator("td");
  await expect(cells).toHaveCount(4);
  const widths = await cells.evaluateAll((elements) =>
    elements.map((element) =>
      Math.round(element.getBoundingClientRect().width),
    ),
  );
  expect(widths.slice(0, 3)).toEqual([28, 28, 14]);
  expect(widths[3]).toBeGreaterThan(
    widths[0]! + widths[1]! + widths[2]!,
  );
}

async function expectDiffHighlightSpansScrollWidth(diff: Locator) {
  const metrics = await diff.evaluate((element) => {
    const viewport = element.querySelector<HTMLElement>(
      ".unified-diff__viewport",
    );
    const table = element.querySelector<HTMLTableElement>("table");
    const changedRow = element.querySelector<HTMLTableRowElement>(
      "tr.is-addition",
    );
    const changedCell = changedRow?.querySelector<HTMLTableCellElement>(
      ".unified-diff__code",
    );
    if (!viewport || !table || !changedRow || !changedCell) return null;
    return {
      clientWidth: viewport.clientWidth,
      scrollWidth: viewport.scrollWidth,
      tableWidth: table.getBoundingClientRect().width,
      rowWidth: changedRow.getBoundingClientRect().width,
      changedBackground: getComputedStyle(changedCell).backgroundColor,
    };
  });

  expect(metrics).not.toBeNull();
  expect(metrics!.scrollWidth).toBeGreaterThan(metrics!.clientWidth);
  expect(Math.abs(metrics!.tableWidth - metrics!.scrollWidth)).toBeLessThanOrEqual(
    1,
  );
  expect(Math.abs(metrics!.rowWidth - metrics!.tableWidth)).toBeLessThanOrEqual(
    1,
  );
  expect(metrics!.changedBackground).not.toBe("rgba(0, 0, 0, 0)");
}
