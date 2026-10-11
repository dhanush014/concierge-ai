import path from "node:path";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { AJA, loginAs, purgeE2EDocuments, purgeInsuranceSince } from "./helpers";

// Fake LLM mode: the fake vision model recognizes the sample cards in data/cards/ by their
// bytes and returns their truth.json values; any other image reads as all empty.
test.describe.configure({ mode: "serial" });

const runStart = new Date().toISOString();
const CARDS = path.resolve(__dirname, "../../data/cards");
const card = (file: string, name: string) => ({ name, mimeType: "image/png", buffer: readFileSync(path.join(CARDS, file)) });

test.beforeAll(async () => {
  await purgeE2EDocuments();
});

test.afterAll(async () => {
  await purgeInsuranceSince(AJA, runStart);
  await purgeE2EDocuments();
});

async function uploadCard(page: Page, file: Parameters<Page["setInputFiles"]>[1]) {
  await page.getByRole("button", { name: "Upload insurance card" }).click();
  await page.getByLabel("Choose file").setInputFiles(file);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByRole("status").first()).toContainText("Uploaded");
}

async function openDocuments(page: Page) {
  await loginAs(page, AJA);
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("heading", { name: "Your documents" })).toBeVisible();
}

const form = (page: Page) => page.locator("section").filter({ has: page.getByRole("heading", { name: "Check your card details" }) });
const summary = (page: Page) => page.locator("section[aria-labelledby=insurance-heading]");

test("1. Read Aja's card: fields filled in, in network, confirm saves it", async ({ page }) => {
  await openDocuments(page);
  await uploadCard(page, card("aja.png", "e2e-aja-card.png"));
  await page.getByRole("button", { name: "Read card e2e-aja-card.png" }).click();

  await expect(form(page)).toBeVisible();
  await expect(page.getByLabel("Insurance company")).toHaveValue("Riverbend Health");
  await expect(page.getByLabel("Member ID")).toHaveValue("RBH556706360");
  await expect(form(page)).toContainText("In network");
  await expect(form(page).getByText("Couldn't read this.")).toHaveCount(0);
  await expect(form(page).getByRole("alert")).toHaveCount(0); // her own name: no warning

  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(form(page)).toHaveCount(0);
  await expect(summary(page)).toContainText("Riverbend Health");
  await expect(summary(page)).toContainText("In network");
  await expect(summary(page)).toContainText("RBH556706360");
});

test("2. Someone else's card: name warning, out of network", async ({ page }) => {
  await openDocuments(page);
  await uploadCard(page, card("marissa.png", "e2e-marissa-card.png"));
  await page.getByRole("button", { name: "Read card e2e-marissa-card.png" }).click();

  await expect(form(page).getByRole("alert")).toContainText("Marissa Dori");
  await expect(form(page)).toContainText("Out of network");
  await page.getByRole("button", { name: "Confirm" }).click(); // still allowed
  await expect(summary(page)).toContainText("Out of network");
});

test("3. Unreadable card: every field highlighted, payer required", async ({ page }) => {
  await openDocuments(page);
  await uploadCard(page, path.join(__dirname, "fixtures", "e2e-card.png"));
  await page.getByRole("button", { name: "Read card e2e-card.png" }).click();

  await expect(form(page).getByText("Couldn't read this. Please type it from your card.")).toHaveCount(5);
  await expect(form(page)).toContainText("We couldn't read 5 fields");
  await expect(form(page)).toContainText("Not on file");

  await page.getByLabel("Insurance company").fill("northstar");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(summary(page)).toContainText("northstar");
  await expect(summary(page)).toContainText("Out of network"); // matched by name, in plain code
});
