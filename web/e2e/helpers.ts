/**
 * E2E test helpers. Runs in Node (Playwright), never in the browser or the Next bundle.
 *
 * Test data is created and deleted through Supabase's REST API with the SERVICE key,
 * which bypasses row-level security. That key is read here from the root .env and is
 * used nowhere else in web/.
 */
import path from "node:path";
import { expect, type Page } from "@playwright/test";
import { addDays, clinicDate, clinicMidnight, formatDayHeading, formatTime, todayInClinic } from "../lib/time";

process.loadEnvFile(path.resolve(__dirname, "../../.env"));

function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is missing from the repo .env`);
  return value;
}

const SUPABASE_URL = env("SUPABASE_URL");
const SERVICE_KEY = env("SUPABASE_SERVICE_KEY");
const ANON_KEY = env("SUPABASE_ANON_KEY");
const API_URL = "http://localhost:8000";

export const AJA = "aja.casper@demo.concierge.test";
export const BART = "bart.brekke@demo.concierge.test";
const E2E_PREFIX = "Dr. E2E";

async function rest<T>(method: string, query: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${SUPABASE_URL}/rest/v1/${query}`, {
    method,
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${method} ${query}: ${resp.status} ${await resp.text()}`);
  const text = await resp.text();
  return (text ? JSON.parse(text) : []) as T;
}

/** Delete every "Dr. E2E…" doctor with its slots and appointments. Returns how many doctors. */
export async function purgeE2EDoctors(): Promise<number> {
  const doctors = await rest<{ id: string }[]>("GET", `doctors?select=id&name=like.${encodeURIComponent(E2E_PREFIX)}*`);
  if (doctors.length === 0) return 0;
  const ids = doctors.map((d) => d.id).join(",");
  const slots = await rest<{ id: string }[]>("GET", `slots?select=id&doctor_id=in.(${ids})`);
  if (slots.length > 0) {
    await rest("DELETE", `appointments?slot_id=in.(${slots.map((s) => s.id).join(",")})`);
  }
  await rest("DELETE", `slots?doctor_id=in.(${ids})`);
  await rest("DELETE", `doctors?id=in.(${ids})`);
  return doctors.length;
}

export async function signIn(email: string): Promise<{ token: string; userId: string }> {
  const resp = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: { apikey: ANON_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: env("DEMO_PASSWORD") }),
  });
  if (!resp.ok) throw new Error(`sign-in ${email}: ${resp.status}. Run the seed script first.`);
  const body = (await resp.json()) as { access_token: string; user: { id: string } };
  return { token: body.access_token, userId: body.user.id };
}

/** Book through the FastAPI backend, as that user. */
export async function bookViaApi(token: string, slotId: string): Promise<number> {
  const resp = await fetch(`${API_URL}/appointments`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ slot_id: slotId }),
  });
  return resp.status;
}

export type TestSlot = { id: string; start: string };

export type World = {
  doctorId: string;
  doctorName: string;
  /** a: book, b: reschedule target, c: the 409 race, consult: 2nd visit type, past: Aja's past visit */
  slots: Record<"a" | "b" | "c" | "consult" | "past", TestSlot>;
};

function at(day: string, hour: number, minute = 0): string {
  return new Date(clinicMidnight(day).getTime() + (hour * 60 + minute) * 60_000).toISOString();
}

/** A fresh test doctor with slots relative to today, plus a past visit for Aja. */
export async function createWorld(): Promise<World> {
  const today = todayInClinic();
  const doctorName = `${E2E_PREFIX} ${Date.now().toString(36)}`;
  const [doctor] = await rest<{ id: string }[]>("POST", "doctors", {
    name: doctorName,
    specialty: "E2E Testing",
  });

  const plan = {
    a: [at(addDays(today, 1), 10), "Checkup"],
    b: [at(addDays(today, 1), 10, 30), "Checkup"],
    c: [at(addDays(today, 2), 10), "Checkup"],
    consult: [at(addDays(today, 2), 11), "Consult"],
    past: [at(addDays(today, -1), 10), "Checkup"],
  } as const;
  const rows = await rest<{ id: string; start_at: string }[]>(
    "POST",
    "slots",
    Object.values(plan).map(([start, type]) => ({
      doctor_id: doctor.id,
      start_at: start,
      end_at: new Date(Date.parse(start) + 30 * 60_000).toISOString(),
      visit_type: type,
    })),
  );
  const byStart = new Map(rows.map((r) => [Date.parse(r.start_at), r.id]));
  const slots = Object.fromEntries(
    Object.entries(plan).map(([key, [start]]) => [key, { id: byStart.get(Date.parse(start))!, start }]),
  ) as World["slots"];

  const aja = await signIn(AJA);
  const [profile] = await rest<{ patient_id: string }[]>("GET", `profiles?select=patient_id&id=eq.${aja.userId}`);
  await rest("POST", "appointments", { patient_id: profile.patient_id, slot_id: slots.past.id });

  return { doctorId: doctor.id, doctorName, slots };
}

/** Accessible name of a slot button, e.g. "Monday, October 12, 10:00 AM EDT". */
export function slotLabel(start: string): string {
  return `${formatDayHeading(clinicDate(start))}, ${formatTime(start)}`;
}

export async function loginAs(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(env("DEMO_PASSWORD"));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/portal\/appointments$/);
}

export function card(page: Page, section: "upcoming" | "past", doctorName: string) {
  return page.locator(`section[aria-labelledby="${section}-heading"] li`).filter({ hasText: doctorName });
}
