import { expect, test } from "@playwright/test";
import { addDays, todayInClinic } from "../lib/time";
import { AJA, assertFakeLlm, createWorld, loginAs, purgeConversationsSince, purgeE2EDoctors, type World } from "./helpers";

// Booking from the chat: the assistant asks for doctor, day and time, finds the slot and
// opens the booking page prefilled; Aja books by pressing Confirm booking there.
// Fake LLM mode: "book with <doctor> on YYYY-MM-DD at HH:MM" makes it look that slot up.

const runStart = new Date().toISOString();
let world: World;

test.beforeAll(async () => {
  await assertFakeLlm();
  world = await createWorld();
});

test.afterAll(async () => {
  await purgeE2EDoctors();
  await purgeConversationsSince(AJA, runStart);
});

const conversation = (page: import("@playwright/test").Page) => page.getByRole("list", { name: "Conversation" });

async function say(page: import("@playwright/test").Page, text: string) {
  const box = page.getByLabel("Your question");
  await box.fill(text);
  await box.press("Enter");
}

test("Aja asks the assistant to book: it asks when, opens the filled-in booking page, she confirms", async ({ page }) => {
  const day = addDays(todayInClinic(), 2); // slot "c": 10:00 AM, Checkup
  await loginAs(page, AJA);
  await page.goto("/portal/ask?c=new");

  await say(page, "Can you book me an appointment?");
  await expect(conversation(page).locator(":scope > li").last()).toContainText("Which doctor");

  await say(page, `Book with ${world.doctorName} on ${day} at 10:00`);
  await expect(page).toHaveURL(new RegExp(`/portal/appointments/book\\?.*slot=${world.slots.c.id}`), { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Step 4 of 4: Review" })).toBeVisible();
  await expect(page.getByText(world.doctorName).first()).toBeVisible();
  await expect(page.getByText("Checkup").first()).toBeVisible();

  // Nothing is booked yet; Back returns to the same conversation, with the button kept.
  await page.goBack();
  const reply = conversation(page).locator(":scope > li").last();
  await expect(reply.getByRole("link", { name: "Review and book" })).toBeVisible();
  await reply.getByRole("link", { name: "Review and book" }).click();

  await page.getByRole("button", { name: "Confirm booking" }).click();
  await expect(page.getByRole("status")).toContainText(`Booked: Checkup with ${world.doctorName}`);
});
