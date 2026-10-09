/**
 * The one place that turns API times (UTC) into clinic time (America/New_York).
 * Dates as "YYYY-MM-DD" strings always mean a clinic-local calendar day.
 * Uses Intl only; no date library.
 */

export const CLINIC_TZ = "America/New_York";

const partsFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: CLINIC_TZ,
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

const ymdFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: CLINIC_TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

type Parts = Record<Intl.DateTimeFormatPartTypes, string>;

function parts(value: string | Date): Parts {
  const date = typeof value === "string" ? new Date(value) : value;
  const out = {} as Parts;
  for (const p of partsFormat.formatToParts(date)) out[p.type] = p.value;
  return out;
}

/** "Wed, Oct 21" */
export function formatDate(value: string | Date): string {
  const p = parts(value);
  return `${p.weekday}, ${p.month} ${p.day}`;
}

/** "1:30 PM EDT" */
export function formatTime(value: string | Date): string {
  const p = parts(value);
  return `${p.hour}:${p.minute} ${p.dayPeriod} ${p.timeZoneName}`;
}

/** "Wed, Oct 21 · 1:30 PM EDT" */
export function formatDateTime(value: string | Date): string {
  return `${formatDate(value)} · ${formatTime(value)}`;
}

/** Clinic-local calendar day of an instant, as "YYYY-MM-DD". */
export function clinicDate(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return ymdFormat.format(date); // en-CA formats as YYYY-MM-DD
}

export function todayInClinic(): string {
  return clinicDate(new Date());
}

export function isYmd(value: string | null | undefined): value is string {
  return !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));
}

/** Calendar arithmetic on "YYYY-MM-DD" (no time zone involved). */
export function addDays(ymd: string, days: number): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** "Wednesday, October 21" for a "YYYY-MM-DD" clinic day. */
export function formatDayHeading(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** Minutes the clinic is ahead of UTC at `instant` (negative in New York). */
function clinicOffsetMinutes(instant: number): number {
  const p = new Intl.DateTimeFormat("en-US", {
    timeZone: CLINIC_TZ,
    hourCycle: "h23",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
  }).formatToParts(new Date(instant));
  const get = (t: string) => Number(p.find((x) => x.type === t)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - instant) / 60000);
}

/** The UTC instant of midnight at the start of a clinic day. DST-safe. */
export function clinicMidnight(ymd: string): Date {
  const [y, m, d] = ymd.split("-").map(Number);
  const guess = Date.UTC(y, m - 1, d);
  let instant = guess - clinicOffsetMinutes(guess) * 60000;
  instant = guess - clinicOffsetMinutes(instant) * 60000; // correct across a DST change
  return new Date(instant);
}
