import { expect, test, type Page } from "@playwright/test";
import { AJA, KIM, loginAs, purgeConversationsSince } from "./helpers";

// Two browsers at once: Aja (patient) and Nurse Kim (staff). Everything Kim and Aja
// see of each other arrives live (Supabase Realtime); neither page is reloaded.
// Fake LLM mode. Conversations (and their handoffs) made here are deleted afterwards.

const runStart = new Date().toISOString();
const tag = `e2e-${Date.now().toString(36)}`; // makes this run's ticket unique in Kim's inbox

test.afterAll(async () => {
  await purgeConversationsSince(AJA, runStart);
});

const conversation = (page: Page) => page.getByRole("list", { name: "Conversation" });
const transcript = (page: Page) => page.getByRole("list", { name: "Transcript" });

async function ajaSays(page: Page, text: string) {
  const box = page.getByLabel("Your question");
  await box.fill(text);
  await box.press("Enter");
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled(); // box cleared
  await expect(page.locator("[aria-busy=true]")).toHaveCount(0); // nothing still streaming
}

test("Aja asks for a person, Nurse Kim joins, replies and closes; the assistant is back", async ({ browser }) => {
  const aja = await (await browser.newContext()).newPage();
  const kim = await (await browser.newContext()).newPage();

  await loginAs(kim, KIM);
  await expect(kim.getByRole("heading", { name: "Staff inbox" })).toBeVisible();
  await loginAs(aja, AJA);
  await aja.goto("/portal/ask?c=new");

  // 1. Aja asks for a human: the agent hands off and goes quiet.
  await ajaSays(aja, `I need to talk to someone (${tag})`);
  await expect(conversation(aja)).toContainText("Connecting you to a nurse");
  await expect(aja.getByText("Connecting you to a nurse… They'll see your messages here.")).toBeVisible();

  // 2. The ticket appears in Kim's open inbox without a refresh, with the AI summary.
  const open = kim.locator("section[aria-labelledby=open-heading]");
  const card = open.getByRole("link").filter({ hasText: tag });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Aja Casper");
  await expect(card).toContainText("Wants a person");
  await card.click();
  await expect(kim.getByRole("heading", { name: "Aja Casper" })).toBeVisible();
  await expect(kim.getByRole("definition").filter({ hasText: `Patient asked: "I need to talk to someone (${tag})"` })).toBeVisible();

  // 3. Kim joins: Aja sees it live.
  await kim.getByRole("button", { name: "Join" }).click();
  await expect(kim.getByText("In progress", { exact: true })).toBeVisible();
  await expect(conversation(aja)).toContainText("Nurse Kim joined the chat.");
  await expect(aja.getByText("You're chatting with Nurse Kim.")).toBeVisible();

  // 4. Kim replies: Aja sees it live, labeled with Kim's name.
  const reply = kim.getByLabel("Reply to the patient");
  await reply.fill("Hi Aja, how can I help?");
  await reply.press("Enter");
  const fromKim = conversation(aja).locator(":scope > li").filter({ hasText: "Hi Aja, how can I help?" });
  await expect(fromKim).toContainText("Nurse Kim");

  // 5. Aja answers: the assistant stays silent, Kim sees it live.
  await ajaSays(aja, "When is my next appointment?");
  await expect(transcript(kim)).toContainText("When is my next appointment?");
  await expect(conversation(aja)).not.toContainText("Here is what I found.");

  // 6. Kim closes: the assistant is back for Aja.
  await kim.getByRole("button", { name: "Close", exact: true }).click();
  await kim.getByRole("button", { name: "Close chat" }).click();
  await expect(kim.getByText(/^Closed /)).toBeVisible();
  await expect(conversation(aja)).toContainText("The assistant is back.");
  await expect(aja.getByText("You're chatting with Nurse Kim.")).toHaveCount(0);

  // 7. The assistant answers again.
  await ajaSays(aja, "When is my next appointment?");
  await expect(conversation(aja).locator(":scope > li").last()).toContainText("Here is what I found.");

  // And the ticket moved to Closed in the inbox.
  await kim.getByRole("link", { name: "Back to inbox" }).click();
  await expect(kim.locator("section[aria-labelledby=closed-heading]").getByRole("link").filter({ hasText: tag })).toBeVisible();
});
