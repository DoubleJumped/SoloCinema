export function formatShowtime(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Regina"
  }).format(new Date(value));
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
