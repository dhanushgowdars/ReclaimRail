const DISPLAY_TIME_ZONE = "Asia/Kolkata";

export function formatMoney(
  amountMinor: number,
  currency = "INR",
  maximumFractionDigits = 0,
): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits,
  }).format(amountMinor / 100);
}

export function formatTimestamp(value: string | Date | null): string {
  if (value === null) return "Not scheduled";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: DISPLAY_TIME_ZONE,
  }).format(typeof value === "string" ? new Date(value) : value);
}

export function formatClockTime(value: string | Date): string {
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: DISPLAY_TIME_ZONE,
  }).format(typeof value === "string" ? new Date(value) : value);
}

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function shortId(value: string, length = 8): string {
  return value.slice(0, length).toUpperCase();
}
