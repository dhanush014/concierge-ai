import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { AJA, loginAs, purgeE2EDocuments } from "./helpers";

// Uploads go to Aja's account; every test file is named "e2e-…" and removed afterwards.
test.describe.configure({ mode: "serial" });

const fixture = (name: string) => path.join(__dirname, "fixtures", name);
const TYPE_ERROR = "That file type isn't supported. Please upload a JPEG, PNG, or PDF.";

test.beforeAll(async () => {
  await purgeE2EDocuments();
});

test.afterAll(async () => {
  await purgeE2EDocuments();
});

async function openDocuments(page: Page) {
  await loginAs(page, AJA);
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("heading", { name: "Your documents" })).toBeVisible();
}

function row(page: Page, filename: string) {
  return page.getByRole("list", { name: "Your documents" }).getByRole("listitem").filter({ hasText: filename });
}

async function upload(page: Page, button: string, file: string) {
  await page.getByRole("button", { name: button }).click();
  await page.getByLabel("Choose file").setInputFiles(fixture(file));
  await expect(page.getByText(file, { exact: true })).toBeVisible(); // name shown before upload
  await page.getByRole("button", { name: "Upload", exact: true }).click();
}

test("upload an image and a PDF, see both listed", async ({ page }) => {
  await openDocuments(page);

  await upload(page, "Upload insurance card", "e2e-card.png");
  await expect(page.getByRole("status")).toHaveText("Uploaded: e2e-card.png.");
  await expect(row(page, "e2e-card.png")).toContainText("Insurance card");

  await upload(page, "Upload referral", "e2e-referral.pdf");
  await expect(page.getByRole("status")).toHaveText("Uploaded: e2e-referral.pdf.");
  await expect(row(page, "e2e-referral.pdf")).toContainText("Referral");

  // Newest first.
  const names = await page.getByRole("list", { name: "Your documents" }).getByRole("listitem").allInnerTexts();
  expect(names.findIndex((t) => t.includes("e2e-referral.pdf"))).toBeLessThan(
    names.findIndex((t) => t.includes("e2e-card.png")),
  );
});

test("View opens the file in a new tab", async ({ page, context }) => {
  await openDocuments(page);

  // Headless Chromium can't display PDFs (it downloads them), so view the image.
  const [tab] = await Promise.all([
    context.waitForEvent("page"),
    row(page, "e2e-card.png").getByRole("button", { name: /^View/ }).click(),
  ]);
  await tab.waitForURL(/\/storage\/v1\/object\/sign\/patient-docs\/.+\.png\?token=/);
  const response = await page.request.get(tab.url());
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("image/png");
  await tab.close();
});

test("delete through the confirm dialog", async ({ page }) => {
  await openDocuments(page);

  const remove = row(page, "e2e-card.png").getByRole("button", { name: "Delete e2e-card.png" });
  await remove.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Delete e2e-card.png? This can't be undone.");

  await dialog.getByRole("button", { name: "Keep document" }).click();
  await expect(dialog).toBeHidden();
  await expect(remove).toBeFocused();

  await remove.click();
  await dialog.getByRole("button", { name: "Delete document" }).click();
  await expect(page.getByRole("status")).toHaveText("Document deleted.");
  await expect(row(page, "e2e-card.png")).toHaveCount(0);
  await expect(row(page, "e2e-referral.pdf")).toHaveCount(1);
});

test("a text file renamed .png is rejected with a plain message", async ({ page }) => {
  await openDocuments(page);

  await upload(page, "Upload insurance card", "e2e-fake.png");
  await expect(page.getByRole("alert").filter({ hasText: TYPE_ERROR })).toBeVisible();
  await expect(row(page, "e2e-fake.png")).toHaveCount(0);
});

test("drag and drop picks the file", async ({ page }) => {
  await openDocuments(page);
  await page.getByRole("button", { name: "Upload referral" }).click();

  // Simulate dropping a file onto the drop zone.
  const dataTransfer = await page.evaluateHandle(() => {
    const dt = new DataTransfer();
    dt.items.add(new File(["%PDF-1.4 dropped"], "e2e-dropped.pdf", { type: "application/pdf" }));
    return dt;
  });
  await page.getByTestId("drop-zone").dispatchEvent("drop", { dataTransfer });

  await expect(page.getByText("e2e-dropped.pdf", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Uploaded: e2e-dropped.pdf.");
});
