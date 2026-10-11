import { expect, test, type Page } from "@playwright/test";
import { AJA, BART, bookViaApi, createWorld, loginAs, purgeConversationsSince, purgeE2EDoctors, signIn, type World } from "./helpers";

// The API runs the fake LLM (see playwright.config.ts): it repeats the tool's records
// back, so replies contain real data without a model. Conversations made here are
// deleted afterwards; older ones stay.
test.describe.configure({ mode: "serial" });

const runStart = new Date().toISOString();
let world: World;

test.beforeAll(async () => {
  world = await createWorld();
  const aja = await signIn(AJA);
  expect(await bookViaApi(aja.token, world.slots.a.id)).toBe(201); // Aja's visit tomorrow
});

test.afterAll(async () => {
  await purgeConversationsSince(AJA, runStart);
  await purgeConversationsSince(BART, runStart);
  await purgeE2EDoctors();
});

const input = (page: Page) => page.getByLabel("Your question");
// Direct items only: a reply's "Sources" list is nested inside its item.
const conversation = (page: Page) => page.getByRole("list", { name: "Conversation" }).locator(":scope > li");
const announcer = (page: Page) => page.locator('.sr-only[role="status"]');
const sendButton = (page: Page) => page.getByRole("button", { name: "Send", exact: true });

async function openNewChat(page: Page, email = AJA) {
  await loginAs(page, email);
  await page.goto("/portal/ask?c=new");
  await expect(page.getByRole("heading", { name: "Ask", level: 1 })).toBeVisible();
}

async function ask(page: Page, text: string) {
  await input(page).fill(text);
  await input(page).press("Enter");
  await expect(page).toHaveURL(/\?c=[0-9a-f-]{36}$/); // set once the reply is done
}

function conversationId(page: Page): string {
  return new URL(page.url()).searchParams.get("c")!;
}

test("1. Suggestion asks about appointments; the answer streams in with real data", async ({ page }) => {
  await openNewChat(page);
  await page.getByRole("button", { name: "When is my next appointment?" }).click();

  await expect(input(page)).toBeFocused(); // focus stays in the input
  const reply = conversation(page).nth(1);
  await expect(reply).toContainText(world.doctorName);
  await expect(reply).toContainText("Here is what I found.");
  // Cited sources under the reply, numbered; the raw [S-xxxx] tags are not shown.
  await expect(reply.getByText("Sources", { exact: true })).toBeVisible();
  await expect(reply.getByRole("listitem").filter({ hasText: world.doctorName }).first()).toBeVisible();
  await expect(reply).toContainText("[1]");
  await expect(reply).not.toContainText("[S-");
  await expect(announcer(page)).toContainText(world.doctorName); // full reply, read once
  await expect(page.getByRole("button", { name: "When is my next appointment?" })).toHaveCount(0);
});

test("2. Emergency: red message with a tap-to-call 911 link", async ({ page }) => {
  await openNewChat(page);
  await ask(page, "I can't breathe");

  const reply = conversation(page).nth(1);
  await expect(reply).toContainText("call 911 now");
  await expect(reply.getByRole("link", { name: "Call 911" })).toHaveAttribute("href", "tel:911");
  await expect(page.getByRole("alert").filter({ hasText: "call 911 now" })).toHaveCount(1);
});

test("3. New conversation starts fresh with its own id", async ({ page }) => {
  await openNewChat(page);
  await ask(page, "hello");
  const first = conversationId(page);

  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(page).toHaveURL(/\?c=new$/);
  await expect(page.getByRole("button", { name: "What documents have I uploaded?" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Conversation" })).toHaveCount(0);

  await ask(page, "hello again");
  expect(conversationId(page)).not.toBe(first);
  await expect(conversation(page)).toHaveCount(2);
});

test("4. Reload keeps the history; the tab reopens the latest conversation", async ({ page }) => {
  await openNewChat(page);
  await ask(page, "can you reschedule my appointment");
  const id = conversationId(page);
  await expect(conversation(page).nth(1)).toContainText("Appointments tab");

  await page.reload();
  await expect(conversation(page)).toHaveCount(2);
  await expect(conversation(page).nth(0)).toContainText("can you reschedule my appointment");

  await page.goto("/portal/ask");
  await expect(page).toHaveURL(new RegExp(`\\?c=${id}$`));
  await expect(conversation(page)).toHaveCount(2);
});

test("5. Bart can't load Aja's conversation", async ({ page, browser }) => {
  await openNewChat(page);
  await ask(page, "a private question from Aja");
  const ajasId = conversationId(page);

  const bart = await (await browser.newContext()).newPage();
  await loginAs(bart, BART);
  await bart.goto(`/portal/ask?c=${ajasId}`);
  await expect(bart.getByText("That conversation isn't available.")).toBeVisible();
  await expect(bart.getByText("a private question from Aja")).toHaveCount(0);
  await bart.context().close();
});

test("6. Phone width, keyboard only: Shift+Enter adds a line, Enter sends", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openNewChat(page);

  await input(page).focus();
  await page.keyboard.type("first line");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("when is my next visit");
  await expect(input(page)).toHaveValue("first line\nwhen is my next visit");
  await expect(sendButton(page)).toBeEnabled();
  await page.keyboard.press("Enter");

  await expect(conversation(page).nth(1)).toContainText(world.doctorName);
  await expect(input(page)).toBeFocused();
  await expect(input(page)).toHaveValue("");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
