import { useEffect, useMemo, useState } from "react";

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
  const d = useMemo(
    () => (typeof date === "string" ? new Date(date) : date),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [typeof date === "string" ? date : date.getTime()],
  );
  const [text, setText] = useState(() => formatRelative(d));
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync initial text then tick
    setText(formatRelative(d));
    const id = setInterval(() => setText(formatRelative(d)), 1000);
    return () => clearInterval(id);
  }, [d]);
  return text;
}
