"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { seerr } from "@/lib/api/seerr";

export function RequestsList() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["seerr", "pending"],
    queryFn: () => seerr.pendingRequests(),
    refetchInterval: 30_000,
  });
  const approve = useMutation({
    mutationFn: (id: number) => seerr.approve(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["seerr"] }),
  });
  const decline = useMutation({
    mutationFn: (id: number) => seerr.decline(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["seerr"] }),
  });

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!data || data.results.length === 0)
    return <p className="text-muted-foreground">No pending requests.</p>;

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {data.results.map((r) => (
        <Card key={r.id}>
          <CardHeader>
            <CardTitle className="text-base">
              {r.media.title ?? `#${r.media.tmdbId}`}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="text-muted-foreground">
              {r.type} · by{" "}
              {r.requestedBy?.displayName ?? r.requestedBy?.username ?? "anon"}
            </div>
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
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
