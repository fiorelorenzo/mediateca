"use client";
import { useEffect, useRef } from "react";

export type OrchestratorEvent =
  | { event: "item.status_changed"; data: { item_id: number; status: string } }
  | { event: "item.search_triggered"; data: { item_id: number } };

export function useOrchestratorEvents(onEvent: (ev: OrchestratorEvent) => void) {
  const cb = useRef(onEvent);
  useEffect(() => {
    cb.current = onEvent;
  });
  useEffect(() => {
    const es = new EventSource("/api/events");
    es.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data);
        cb.current(parsed);
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => {
      /* let browser auto-reconnect */
    };
    return () => es.close();
  }, []);
}
