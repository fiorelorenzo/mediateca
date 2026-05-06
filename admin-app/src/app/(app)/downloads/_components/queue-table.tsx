"use client";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { arrs } from "@/lib/api/arrs";

function pct(total: number, left: number) {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((1 - left / total) * 100)));
}

export function QueueTable() {
  const { data } = useQuery({ queryKey: ["arrs", "queue"], queryFn: () => arrs.unifiedQueue(), refetchInterval: 5_000 });
  if (!data) return null;
  if (data.length === 0) return <p className="text-muted-foreground">Queue empty.</p>;
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead className="w-24">Kind</TableHead>
            <TableHead className="w-32">Status</TableHead>
            <TableHead className="w-32 text-right">Progress</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((q) => (
            <TableRow key={`${q.kind}-${q.id}`}>
              <TableCell>{q.title}</TableCell>
              <TableCell><Badge variant="outline">{q.kind}</Badge></TableCell>
              <TableCell>{q.status}</TableCell>
              <TableCell className="text-right text-muted-foreground">{pct(q.size, q.sizeleft)}%</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
