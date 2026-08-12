/**
 * Display formatting.
 *
 * Every formatter pins the locale to `en-GB`. That is not laziness about i18n:
 * these views render on the server and again on the client, and a formatter
 * that reads the visitor's locale produces a different string in each pass and
 * a hydration mismatch. A fixed locale also gives engineering-unambiguous
 * dates (10 Aug 2026, never 08/10/2026), which matters on records that carry
 * legal weight.
 */

const LOCALE = "en-GB";

const dateOnly = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const dateAndTime = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

const timeOnly = new Intl.DateTimeFormat(LOCALE, {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

/** `2026-08-10` or an ISO timestamp → `10 Aug 2026`. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  return Number.isNaN(parsed.valueOf()) ? "—" : dateOnly.format(parsed);
}

/** An ISO timestamp → `10 Aug 2026 17:44`. */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "—" : dateAndTime.format(parsed);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "—" : timeOnly.format(parsed);
}

/**
 * Whole days from today, signed. Negative is in the past. Returns null for a
 * missing date so callers can choose their own empty rendering.
 */
export function daysFromToday(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(parsed.valueOf())) return null;
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((parsed.valueOf() - today) / 86_400_000);
}

/** `-12` → `12 days overdue`; `40` → `in 40 days`; `0` → `today`. */
export function formatDayOffset(days: number | null): string {
  if (days === null) return "—";
  if (days === 0) return "today";
  if (days < 0) return `${Math.abs(days)} ${Math.abs(days) === 1 ? "day" : "days"} overdue`;
  return `in ${days} ${days === 1 ? "day" : "days"}`;
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Drops trailing zeros — `2.0000` → `2`, `0.15` → `0.15`. */
export function formatQuantity(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 4 }).format(value);
}

export function formatMoney(
  value: number | null | undefined,
  currency = "EUR",
  digits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined) return "—";
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${formatNumber(milliseconds / 1000, 1)} s`;
}

/**
 * `technical_validation` → `Technical validation`. The API hands back database
 * enum members in several shapes; no screen should ever print one raw.
 */
export function humanise(value: string | null | undefined): string {
  if (!value) return "—";
  const spaced = value.replace(/[_-]+/g, " ").trim();
  if (!spaced) return "—";
  // Already prose or an acronym the domain uses — leave it alone.
  if (/[a-z]/.test(spaced) && /^[A-Z]/.test(spaced)) return spaced;
  if (spaced === spaced.toUpperCase() && spaced.length <= 5) return spaced;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}
