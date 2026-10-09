import { expect, test } from "@playwright/test";
import { addDays, formatDate, formatDateTime, formatTime, todayInClinic } from "../lib/time";
import {
  AJA,
  BART,
  bookViaApi,
  card,
  createWorld,
  loginAs,
  purgeE2EDoctors,
  signIn,
  slotLabel,
  type World,
} from "./helpers";

// One shared test doctor; tests run in order (book -> reschedule -> cancel).
test.describe.configure({ mode: "serial" });

let world: World;

test.beforeAll(async () => {
  world = await createWorld();
});

test.afterAll(async () => {
  await purgeE2EDoctors();
});

function bookUrl(extra: Record<string, string> = {}): string {
  const query = new URLSearchParams({ doctor: world.doctorId, type: "Checkup", ...extra });
  return `/portal/appointments/book?${query}`;
}

test("1. Aja books a visit and sees it under Upcoming", async ({ page }) => {
  const { a } = world.slots;
  await loginAs(page, AJA);

  await page.getByRole("link", { name: "Book a visit" }).first().click();
  await page.getByRole("link", { name: new RegExp(world.doctorName) }).click();
  await expect(page.getByRole("heading", { name: "Step 2 of 4: Choose a visit type" })).toBeVisible();
  await page.getByRole("link", { name: "Checkup" }).click();

  const slot = page.getByRole("button", { name: slotLabel(a.start) });
  await slot.click();
  await expect(slot).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Step 4 of 4: Review" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm booking" }).click();

  await expect(page.getByRole("status")).toHaveText(
    `Booked: Checkup with ${world.doctorName} on ${formatDate(a.start)} at ${formatTime(a.start)}.`,
  );
  await expect(card(page, "upcoming", world.doctorName)).toContainText(formatDateTime(a.start));
});

test("2. Aja reschedules: the old time is gone, the new time shows", async ({ page }) => {
  const { a, b } = world.slots;
  await loginAs(page, AJA);

  await card(page, "upcoming", world.doctorName).getByRole("link", { name: /^Reschedule Checkup/ }).click();
  await page.getByRole("button", { name: slotLabel(b.start) }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(formatDateTime(a.start))).toHaveCount(2); // current + "From"
  await expect(page.getByText(formatDateTime(b.start))).toBeVisible(); // "To"
  await page.getByRole("button", { name: "Confirm new time" }).click();

  await expect(page.getByRole("status")).toContainText("Rescheduled: Checkup");
  const upcoming = card(page, "upcoming", world.doctorName);
  await expect(upcoming).toHaveCount(1);
  await expect(upcoming).toContainText(formatDateTime(b.start));
  await expect(upcoming).not.toContainText(formatDateTime(a.start));
});

test("3. Aja cancels through the dialog", async ({ page }) => {
  const { b } = world.slots;
  await loginAs(page, AJA);

  const cancel = card(page, "upcoming", world.doctorName).getByRole("button", { name: /^Cancel Checkup/ });
  await cancel.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`Cancel your Checkup on ${formatDate(b.start)} at ${formatTime(b.start)}?`);

  // Escape closes it and returns focus to the button that opened it.
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(cancel).toBeFocused();

  await cancel.click();
  await dialog.getByRole("button", { name: "Cancel appointment" }).click();
  await expect(page.getByRole("status")).toHaveText("Appointment cancelled.");
  await expect(card(page, "upcoming", world.doctorName)).toHaveCount(0);
});

test("4. Past appointments have no buttons", async ({ page }) => {
  await loginAs(page, AJA);

  const past = card(page, "past", world.doctorName);
  await expect(past).toContainText(formatDateTime(world.slots.past.start));
  await expect(past.getByRole("button")).toHaveCount(0);
  await expect(past.getByRole("link")).toHaveCount(0);
});

test("5. Slot taken while reviewing: 'someone just booked' and back to the times", async ({ page }) => {
  const { c } = world.slots;
  await loginAs(page, AJA);
  await page.goto(bookUrl({ slot: c.id }));
  await expect(page.getByRole("heading", { name: "Step 4 of 4: Review" })).toBeVisible();

  const bart = await signIn(BART);
  expect(await bookViaApi(bart.token, c.id)).toBe(201);

  await page.getByRole("button", { name: "Confirm booking" }).click();
  await expect(page.getByRole("status")).toHaveText("Sorry, someone just booked that time. Please pick another.");
  await expect(page.getByRole("heading", { name: "Step 3 of 4: Choose a time" })).toBeVisible();
  await expect(page.getByRole("button", { name: slotLabel(c.start) })).toHaveCount(0);
});

test("6. Logged out, /portal/appointments goes to /login", async ({ page }) => {
  await page.goto("/portal/appointments");
  await expect(page).toHaveURL(/\/login$/);
});

test("7. Time window: never before today, 2 weeks at a time", async ({ page }) => {
  const today = todayInClinic();
  await loginAs(page, AJA);

  await page.goto(bookUrl({ from: addDays(today, -30) })); // a past date in the URL is clamped
  const previous = page.getByRole("button", { name: "Previous 2 weeks" });
  await expect(previous).toBeDisabled();
  await expect(page.getByRole("listitem").filter({ hasText: "No openings" }).first()).toBeVisible();

  await page.getByRole("button", { name: "Next 2 weeks" }).click();
  await expect(page).toHaveURL(new RegExp(`from=${addDays(today, 14)}`));
  await expect(previous).toBeEnabled();

  await previous.click();
  await expect(page).not.toHaveURL(/from=/);
  await expect(previous).toBeDisabled();
});

test("8. Phone width (375px): no sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await loginAs(page, AJA);
  const pages = [
    "/portal/appointments",
    "/portal/appointments/book",
    bookUrl(),
    bookUrl({ slot: world.slots.consult.id, type: "Consult" }),
  ];
  for (const url of pages) {
    await page.goto(url);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Loading…")).toHaveCount(0);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, url).toBeLessThanOrEqual(0);
  }
});
