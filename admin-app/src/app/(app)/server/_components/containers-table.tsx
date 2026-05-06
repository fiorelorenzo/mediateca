"use client";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";

const STATUS_VARIANT = { running: "default", restarting: "secondary", exited: "destructive", paused: "outline" } as const;

export function ContainersTable() {
  const { data } = useQuery({
    queryKey: ["metrics", "containers"],
    queryFn: () => api.containers(),
    refetchInterval: 10_000,
  });
  if (!data) return null;
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead className="w-32">Status</TableHead>
            <TableHead>Image</TableHead>
            <TableHead className="w-32 text-right">Memory</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((c) => (
            <TableRow key={c.name}>
              <TableCell className="font-medium">{c.name}</TableCell>
              <TableCell>
                <Badge variant={STATUS_VARIANT[c.status as keyof typeof STATUS_VARIANT] ?? "outline"}>{c.status}</Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">{c.image}</TableCell>
              <TableCell className="text-right text-muted-foreground">{c.mem ? `${(c.mem / 1024 / 1024).toFixed(0)} MB` : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
