const REGINA_TIME_ZONE = "America/Regina";

export function formatShowtime(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone: REGINA_TIME_ZONE
  }).format(new Date(value));
}

export function getReginaDay(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: REGINA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(value));
}

export function getReginaHour(value: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: REGINA_TIME_ZONE,
    hour: "2-digit",
    hourCycle: "h23"
  }).formatToParts(new Date(value));
  const hour = parts.find((part) => part.type === "hour");
  return Number(hour?.value ?? "0");
}

export function formatDayLabel(day: string) {
  // Regina stays on CST (UTC-6) year-round, so anchoring to noon -06:00
  // always lands on the intended calendar day.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: REGINA_TIME_ZONE,
    weekday: "short",
    month: "short",
    day: "numeric"
  }).format(new Date(`${day}T12:00:00-06:00`));
}

export function formatBoardTime(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: REGINA_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).format(new Date(value));
}

export function formatBoardDate(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: REGINA_TIME_ZONE,
    month: "short",
    day: "numeric"
  })
    .format(new Date(value))
    .replaceAll(".", "")
    .toUpperCase();
}

export function formatRelativeCheck(value: string, now = new Date()) {
  const diffMs = Math.max(0, now.getTime() - new Date(value).getTime());
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) {
    return "just now";
  }
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} hr ago`;
  }
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}
