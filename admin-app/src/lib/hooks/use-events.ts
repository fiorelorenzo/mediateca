"use client";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

export type OrchestratorEvent =
  | { event: "item.status_changed"; data: { item_id: number; status: string } }
  | { event: "item.search_triggered"; data: { item_id: number } }
  | { event: "retention.proposed"; data: Record<string, unknown> }
  | { event: "retention.graced"; data: Record<string, unknown> }
  | { event: "retention.deleted"; data: Record<string, unknown> }
  | { event: "retention.refetched"; data: Record<string, unknown> }
  | { event: "retention.disk_pressure"; data: Record<string, unknown> }
  | { event: "retention.pinned"; data: Record<string, unknown> }
  | { event: "retention.refetch_failed"; data: Record<string, unknown> }
  | { event: "retention.disk_pressure_unresolved"; data: Record<string, unknown> };

export function useOrchestratorEvents(onEvent: (ev: OrchestratorEvent) => void) {
  const cb = useRef(onEvent);
  const qc = useQueryClient();
  useEffect(() => {
    cb.current = onEvent;
  });
  useEffect(() => {
    const es = new EventSource("/api/events");
    es.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as OrchestratorEvent;
        // Retention events fan out to several widgets (overview, proposals,
        // lifecycle); invalidating the broad key keeps them all in sync without
        // each consumer having to subscribe.
        if (typeof parsed.event === "string" && parsed.event.startsWith("retention.")) {
          qc.invalidateQueries({ queryKey: ["retention"] });
        }
        cb.current(parsed);
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => {
      /* let browser auto-reconnect */
    };
    return () => es.close();
  }, [qc]);
}
