import { useEffect, useState } from "react";

export function formatRelative(date: Date, now: Date = new Date()): string {
  const diff = now.getTime() - date.getTime();
  const s = Math.floor(diff / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function useRelativeTime(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const [text, setText] = useState(() => formatRelative(d));
  useEffect(() => {
    setText(formatRelative(d));
    const id = setInterval(() => setText(formatRelative(d)), 1000);
    return () => clearInterval(id);
  }, [d]);
  return text;
}
