"use client";

import { type ReactNode } from "react";

export function TimelineHeader({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 lg:grid-cols-5">{children}</div>;
}
