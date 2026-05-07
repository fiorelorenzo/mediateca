"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CardsSkeleton } from "@/components/skeletons/cards-skeleton";
import { EmptyState } from "@/components/empty-state";
import { seerr } from "@/lib/api/seerr";

type Filter = "pending" | "approved" | "declined" | "all";

const STATUS = { 1: "pending", 2: "approved", 3: "declined" } as const;

export function RequestsList() {
  const [filter, setFilter] = useState<Filter>("pending");
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["seerr", filter],
    queryFn: () =>
      filter === "pending"
        ? seerr.pendingRequests()
        : seerr.allRequests(filter),
    refetchInterval: 30_000,
  });

  const approve = useMutation({
    mutationFn: (id: number) => seerr.approve(id),
    onSuccess: () => {
      toast.success("Request approved");
      qc.invalidateQueries({ queryKey: ["seerr"] });
    },
    onError: (e) => toast.error(`Approve failed: ${(e as Error).message}`),
  });
  const decline = useMutation({
    mutationFn: (id: number) => seerr.decline(id),
    onSuccess: () => {
      toast.success("Request declined");
      qc.invalidateQueries({ queryKey: ["seerr"] });
    },
    onError: (e) => toast.error(`Decline failed: ${(e as Error).message}`),
  });

  const filters: Filter[] = ["pending", "approved", "declined", "all"];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={
              "rounded-full border px-3 py-1 text-sm transition " +
              (filter === f
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:border-foreground hover:text-foreground")
            }
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {isLoading ? (
        <CardsSkeleton count={6} />
      ) : (data?.results?.length ?? 0) === 0 ? (
        <EmptyState
          icon={Inbox}
          title="No requests"
          description="Nothing pending right now."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data!.results.map((r) => (
            <Card key={r.id}>
              <CardHeader>
                <CardTitle className="text-base">
                  {r.media?.title ?? `#${r.media?.tmdbId}`}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="text-muted-foreground">
                  {r.type} · by{" "}
                  {r.requestedBy?.displayName ??
                    r.requestedBy?.username ??
                    "anon"}{" "}
                  · {STATUS[r.status as 1 | 2 | 3] ?? "?"}
                </div>
                {r.status === 1 && (
                  <div className="flex gap-2 pt-2">
                    <Button
                      size="sm"
                      onClick={() => approve.mutate(r.id)}
                      disabled={approve.isPending}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => decline.mutate(r.id)}
                      disabled={decline.isPending}
                    >
                      Decline
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
