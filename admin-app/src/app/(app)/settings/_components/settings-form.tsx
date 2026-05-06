"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import type { Settings } from "@/lib/api/types";

interface FormProps {
  initial: Settings;
}

function SettingsFormInner({ initial }: FormProps) {
  const qc = useQueryClient();
  const [langs, setLangs] = useState(initial.required_audio_langs.join(","));
  const [retry, setRetry] = useState(initial.retry_interval_hours);
  const [hls, setHls] = useState(initial.hls_enabled);
  const [acceptAfter, setAcceptAfter] = useState(initial.accept_as_is_after_attempts);

  const save = useMutation({
    mutationFn: (s: Partial<Settings>) => api.putSettings(s),
    onSuccess: (next) => qc.setQueryData(["settings"], next),
  });

  return (
    <form
      className="max-w-xl space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({
          required_audio_langs: langs
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          retry_interval_hours: Number(retry),
          accept_as_is_after_attempts: Number(acceptAfter),
          hls_enabled: hls,
        });
      }}
    >
      <div className="space-y-2">
        <Label htmlFor="langs">Required audio languages</Label>
        <Input
          id="langs"
          value={langs}
          onChange={(e) => setLangs(e.target.value)}
          placeholder="ita, @original"
        />
        <p className="text-sm text-muted-foreground">
          ISO-639-2 codes; <code>@original</code> resolves per-item.
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="retry">Retry interval (hours)</Label>
        <Input
          id="retry"
          type="number"
          min={1}
          value={retry}
          onChange={(e) => setRetry(Number(e.target.value))}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="acceptAfter">Auto-freeze after N retries (0 = never)</Label>
        <Input
          id="acceptAfter"
          type="number"
          min={0}
          value={acceptAfter}
          onChange={(e) => setAcceptAfter(Number(e.target.value))}
        />
      </div>

      <div className="flex items-center gap-3 rounded-lg border p-3">
        <Switch id="hls" checked={hls} onCheckedChange={setHls} />
        <div>
          <Label htmlFor="hls">HLS encoding</Label>
          <p className="text-sm text-muted-foreground">
            When off, files are promoted as-is. Container must be running.
          </p>
        </div>
      </div>

      <Button type="submit" disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save"}
      </Button>
      {save.isSuccess && <span className="ml-3 text-sm text-emerald-600">Saved.</span>}
    </form>
  );
}

export function SettingsForm() {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });

  if (!data) return null;

  return <SettingsFormInner key={data.required_audio_langs.join(",")} initial={data} />;
}
