"use client";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

export function TrashSyncButton() {
  const m = useMutation({ mutationFn: api.recyclarrSync });
  return (
    <div className="flex items-center gap-3">
      <Button onClick={() => m.mutate()} disabled={m.isPending}>
        {m.isPending ? "Starting…" : "Sync now"}
      </Button>
      {m.isSuccess && <span className="text-sm text-emerald-600">Sync started.</span>}
      {m.isError && <span className="text-sm text-destructive">{(m.error as Error).message}</span>}
    </div>
  );
}
