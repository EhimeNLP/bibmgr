import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const email = "e2e.visitor@example.org";

test("authenticated access, CRUD, restore, and accessibility", async ({
  page,
  request,
}) => {
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

  await page.getByRole("button", { name: "Add reference" }).click();
  await page.getByLabel("BibTeX entry").fill(
    [
      "@article{bibmgre2e2026,",
      "  author = {Researcher, Example},",
      "  title = {End-to-End Reference},",
      "  journal = {Transactions of the Association for Computational Linguistics},",
      "  year = {2026},",
      "  doi = {10.9999/bibmgr-e2e},",
      "  url = {https://example.org/bibmgr-e2e},",
      "}",
      "",
    ].join("\n"),
  );
  await registerAndWaitForCompletion(page);
  await page.getByRole("button", { name: "Close add references" }).click();

  await page
    .getByRole("searchbox", { name: "Search references" })
    .fill("End-to-End Reference");
  await page.getByRole("button", { name: "Search references" }).click();
  await expect(
    page.getByRole("button", { name: /End-to-End Reference/ }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Reference actions" }).click();
  await page.getByRole("menuitem", { name: "Edit…" }).click();
  const editor = page.getByRole("textbox", {
    name: "Reference BibTeX entry",
  });
  await editor.fill(
    (await editor.inputValue()).replace(
      "End-to-End Reference",
      "Edited End-to-End Reference",
    ),
  );
  await saveAndWaitForDialogToClose(page);
  await expect(
    page
      .getByRole("region", { name: "Reference details" })
      .getByRole("heading", {
        name: "Edited End-to-End Reference",
        level: 2,
      }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Reference actions" }).click();
  await page.getByRole("menuitem", { name: "Delete…" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Edited End-to-End Reference" }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Reference history" }).click();
  await page.getByRole("button", { name: /Edited End-to-End Reference/ }).click();
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
