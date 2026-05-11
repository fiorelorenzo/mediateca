"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Check } from "lucide-react";
import { toast } from "sonner";

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
  const [qualityUpgrade, setQualityUpgrade] = useState(initial.quality_upgrade_enabled);
  const [acceptAfter, setAcceptAfter] = useState(initial.accept_as_is_after_attempts);
  const [durationThreshold, setDurationThreshold] = useState(
    initial.merge_duration_reject_threshold_s,
  );
  const [offsetSafe, setOffsetSafe] = useState(initial.merge_offset_safe_ms);
  const [offsetReject, setOffsetReject] = useState(initial.merge_offset_reject_ms);

  const offsetError =
    offsetReject <= offsetSafe
      ? "Audio offset reject threshold must be greater than safe limit."
      : null;

  const save = useMutation({
    mutationFn: (s: Partial<Settings>) => api.putSettings(s),
    onSuccess: (next) => {
      qc.setQueryData(["settings"], next);
      toast.success("Settings saved");
    },
    onError: (e) => toast.error(`Save failed: ${(e as Error).message}`),
  });

  return (
    <form
      className="max-w-xl space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (offsetError) return;
        save.mutate({
          required_audio_langs: langs
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          retry_interval_hours: Number(retry),
          accept_as_is_after_attempts: Number(acceptAfter),
          hls_enabled: hls,
          quality_upgrade_enabled: qualityUpgrade,
          merge_duration_reject_threshold_s: Number(durationThreshold),
          merge_offset_safe_ms: Number(offsetSafe),
          merge_offset_reject_ms: Number(offsetReject),
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
        <p className="text-muted-foreground text-sm">
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
          <p className="text-muted-foreground text-sm">
            When off, files are promoted as-is. Container must be running.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 rounded-lg border p-3">
        <Switch
          id="qualityUpgrade"
          checked={qualityUpgrade}
          onCheckedChange={setQualityUpgrade}
        />
        <div>
          <Label htmlFor="qualityUpgrade">Quality upgrades on PROMOTED items</Label>
          <p className="text-muted-foreground text-sm">
            When on, the orchestrator stops un-monitoring after promote — Sonarr/Radarr can
            grab a better release later and the pipeline replaces the library file in place
            (no merge) as long as the new audio is a superset (no language regression). Off
            by default: 4K Remux churn can be expensive in storage and bandwidth.
          </p>
        </div>
      </div>

      {/* ── Merge safety ─────────────────────────────────────────────────── */}
      <div className="space-y-4 rounded-lg border p-4">
        <p className="text-sm font-semibold">Merge safety</p>

        <div className="space-y-2">
          <Label htmlFor="durationThreshold">Duration reject threshold (seconds)</Label>
          <Input
            id="durationThreshold"
            type="number"
            min={0.1}
            step={0.5}
            value={durationThreshold}
            onChange={(e) => setDurationThreshold(Number(e.target.value))}
          />
          <p className="text-muted-foreground text-sm">
            Merge is rejected if the two files differ in duration by more than this value.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="offsetSafe">Audio offset safe limit (ms)</Label>
          <Input
            id="offsetSafe"
            type="number"
            min={0}
            step={10}
            value={offsetSafe}
            onChange={(e) => setOffsetSafe(Number(e.target.value))}
          />
          <p className="text-muted-foreground text-sm">
            Tracks are considered perfectly aligned when the detected offset is below this value.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="offsetReject">Audio offset reject threshold (ms)</Label>
          <Input
            id="offsetReject"
            type="number"
            min={1}
            step={100}
            value={offsetReject}
            onChange={(e) => setOffsetReject(Number(e.target.value))}
          />
          <p className="text-muted-foreground text-sm">
            Merge is rejected when the detected audio drift exceeds this value (must be &gt; safe
            limit).
          </p>
          {offsetError && <p className="text-destructive text-sm">{offsetError}</p>}
        </div>
      </div>

      <Button type="submit" disabled={save.isPending || !!offsetError}>
        <AnimatePresence mode="wait">
          {save.isSuccess ? (
            <motion.span
              key="ok"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              className="flex items-center gap-1"
            >
              <Check className="size-4" /> Saved
            </motion.span>
          ) : save.isPending ? (
            <motion.span key="loading">Saving…</motion.span>
          ) : (
            <motion.span key="idle">Save</motion.span>
          )}
        </AnimatePresence>
      </Button>
    </form>
  );
}

export function SettingsForm() {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });

  if (!data) return null;

  return <SettingsFormInner key={data.required_audio_langs.join(",")} initial={data} />;
}
