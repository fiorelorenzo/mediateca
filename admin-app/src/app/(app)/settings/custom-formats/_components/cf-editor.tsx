"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cfApi, type CustomFormat } from "@/lib/api/client";

export function CFEditor() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["cf"], queryFn: () => cfApi.list() });
  const create = useMutation({
    mutationFn: cfApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cf"] }),
  });
  const remove = useMutation({
    mutationFn: cfApi.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cf"] }),
  });

  const [name, setName] = useState("");
  const [score, setScore] = useState(100);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Add custom format</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!name) return;
              create.mutate({ name, score, spec: {} });
              setName("");
            }}
          >
            <div className="flex-1 min-w-48 space-y-1">
              <Label htmlFor="cfname">Name</Label>
              <Input id="cfname" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="w-28 space-y-1">
              <Label htmlFor="cfscore">Score</Label>
              <Input
                id="cfscore"
                type="number"
                value={score}
                onChange={(e) => setScore(Number(e.target.value))}
              />
            </div>
            <Button type="submit" disabled={create.isPending}>
              Add
            </Button>
          </form>
          <p className="mt-2 text-sm text-muted-foreground">
            Spec edits via JSON: open the row to expand.
          </p>
        </CardContent>
      </Card>

      <div className="space-y-2">
        {list.data?.map((cf: CustomFormat) => (
          <Card key={cf.id}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle className="text-base">{cf.name}</CardTitle>
                <p className="text-sm text-muted-foreground">score {cf.score}</p>
              </div>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => remove.mutate(cf.id)}
              >
                Delete
              </Button>
            </CardHeader>
            <CardContent>
              <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">
                {JSON.stringify(cf.spec, null, 2)}
              </pre>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
