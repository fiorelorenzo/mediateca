import Link from "next/link";

import { cn } from "@/lib/utils/cn";

interface StageCardProps {
  title: string;
  href: string;
  primary: { value: number | string; label: string };
  secondary?: { value: number | string; label: string }[];
  accent?: "default" | "warn" | "danger";
}

export function StageCard({ title, href, primary, secondary, accent = "default" }: StageCardProps) {
  return (
    <Link
      href={href}
      className={cn(
        "flex h-full flex-col rounded-lg border bg-card p-4 transition hover:bg-accent",
        accent === "warn" && "border-amber-400/40",
        accent === "danger" && "border-red-400/40",
      )}
    >
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <div className="text-3xl font-semibold tabular-nums">{primary.value}</div>
        <div className="text-xs text-muted-foreground">{primary.label}</div>
      </div>
      {secondary?.length ? (
        <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
          {secondary.map((s, i) => (
            <li key={i} className="flex justify-between">
              <span>{s.label}</span>
              <span className="tabular-nums">{s.value}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </Link>
  );
}
