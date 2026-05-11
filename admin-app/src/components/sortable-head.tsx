"use client";

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { TableHead } from "@/components/ui/table";

export type SortDir = "asc" | "desc";
export type SortState<K extends string> = { key: K; dir: SortDir } | null;

/** Returns the next state in the asc → desc → off cycle for the clicked key. */
export function nextSort<K extends string>(prev: SortState<K>, key: K): SortState<K> {
  if (prev?.key !== key) return { key, dir: "asc" };
  if (prev.dir === "asc") return { key, dir: "desc" };
  return null;
}

interface SortableHeadProps<K extends string> {
  label: string;
  sortKey: K;
  sort: SortState<K>;
  onSort: (k: K) => void;
  align?: "left" | "right";
  className?: string;
}

export function SortableHead<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  align = "left",
  className,
}: SortableHeadProps<K>) {
  const active = sort?.key === sortKey;
  const Icon = !active ? ArrowUpDown : sort?.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`hover:text-foreground inline-flex items-center gap-1 text-xs uppercase tracking-wide transition-colors ${
          align === "right" ? "ml-auto flex w-full justify-end" : ""
        } ${active ? "text-foreground" : "text-muted-foreground"}`}
      >
        <span>{label}</span>
        <Icon className={`size-3 ${active ? "" : "opacity-50"}`} />
      </button>
    </TableHead>
  );
}
