"use client";

import type { ReactNode } from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface PipelineColumn<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
}

interface Props<T> {
  rows: T[];
  columns: PipelineColumn<T>[];
  rowKey: (row: T) => string | number;
  empty?: ReactNode;
}

export function PipelineTable<T>({ rows, columns, rowKey, empty }: Props<T>) {
  if (rows.length === 0) {
    return (
      <div className="rounded border border-dashed p-6 text-sm text-muted-foreground">
        {empty ?? "Nothing here yet."}
      </div>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((c) => (
            <TableHead key={c.key} className={c.className}>
              {c.header}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={rowKey(r)}>
            {columns.map((c) => (
              <TableCell key={c.key} className={c.className}>
                {c.cell(r)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
