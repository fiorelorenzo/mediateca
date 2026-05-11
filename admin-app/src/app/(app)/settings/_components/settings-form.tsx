"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Check, Eye, EyeOff, Trash2, Send, Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import type { NotificationChannel, Settings } from "@/lib/api/types";

interface FormProps {
  initial: Settings;
}

function maskUrl(url: string): string {
  // Hide passwords/tokens between :// and @ (mailto://user:PASS@host) and any
  // trailing /<token> for tgram://, discord://, etc.
  return url
    .replace(/(:\/\/[^:/@]+:)([^@]+)(@)/, (_m, a, _b, c) => `${a}••••${c}`)
    .replace(/(\/)([A-Za-z0-9_-]{20,})/g, (_m, a) => `${a}••••`);
}

function ChannelsEditor({
  value,
  onChange,
}: {
  value: NotificationChannel[];
  onChange: (next: NotificationChannel[]) => void;
}) {
  const [reveal, setReveal] = useState<Record<number, boolean>>({});
  const [draft, setDraft] = useState<NotificationChannel>({ name: "", url: "", enabled: true });
  const [busyIdx, setBusyIdx] = useState<number | null>(null);

  const updateAt = (i: number, patch: Partial<NotificationChannel>) =>
    onChange(value.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));

  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));

  const add = () => {
    if (!draft.name.trim() || !draft.url.trim()) {
      toast.error("Name and URL are required");
      return;
    }
    if (value.some((c) => c.name.trim() === draft.name.trim())) {
      toast.error("A channel with that name already exists");
      return;
    }
    onChange([...value, { ...draft, name: draft.name.trim(), url: draft.url.trim() }]);
    setDraft({ name: "", url: "", enabled: true });
  };

  const test = async (i: number) => {
    setBusyIdx(i);
    try {
      const r = await api.testNotification(value[i].url);
      if (r.ok) toast.success(`Test sent to ${value[i].name}`);
      else toast.error(`Test failed: ${r.message}`);
    } catch (e) {
      toast.error(`Test error: ${(e as Error).message}`);
    } finally {
      setBusyIdx(null);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">Channels</p>
      {value.length === 0 && (
        <p className="text-muted-foreground rounded-md border border-dashed p-3 text-sm">
          No channels configured. Add one below to start receiving notifications.
        </p>
      )}
      {value.map((c, i) => (
        <div key={i} className="space-y-2 rounded-md border p-3">
          <div className="flex items-center gap-2">
            <Input
              className="flex-1"
              value={c.name}
              onChange={(e) => updateAt(i, { name: e.target.value })}
              placeholder="Name (e.g. Personal Email)"
            />
            <Switch
              checked={c.enabled}
              onCheckedChange={(checked) => updateAt(i, { enabled: checked })}
              aria-label="Enable channel"
            />
          </div>
          <div className="flex items-center gap-2">
            <Input
              className="flex-1 font-mono text-xs"
              value={reveal[i] ? c.url : maskUrl(c.url)}
              onChange={(e) => updateAt(i, { url: e.target.value })}
              disabled={!reveal[i]}
              placeholder="mailto://... or tgram://... or ntfy://..."
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setReveal({ ...reveal, [i]: !reveal[i] })}
              aria-label={reveal[i] ? "Hide URL" : "Reveal URL"}
            >
              {reveal[i] ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => test(i)}
              disabled={busyIdx === i || !c.url.trim()}
              aria-label="Send test notification"
            >
              <Send className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => remove(i)}
              aria-label="Delete channel"
            >
              <Trash2 className="text-destructive size-4" />
            </Button>
          </div>
        </div>
      ))}
      <div className="space-y-2 rounded-md border border-dashed p-3">
        <p className="text-sm font-medium">Add a channel</p>
        <Input
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          placeholder="Name"
        />
        <Input
          className="font-mono text-xs"
          value={draft.url}
          onChange={(e) => setDraft({ ...draft, url: e.target.value })}
          placeholder="mailtos://user:apppass@gmail.com?to=you@x.com"
        />
        <div className="flex justify-end">
          <Button type="button" variant="outline" size="sm" onClick={add}>
            <Plus className="size-4" /> Add
          </Button>
        </div>
      </div>
      <p className="text-muted-foreground text-xs">
        Changes save together with the rest of the form. Use the paper-plane button to verify a
        channel before saving.
      </p>
    </div>
  );
}

function SettingsFormInner({ initial }: FormProps) {
  const qc = useQueryClient();
  const [langs, setLangs] = useState(initial.required_audio_langs.join(","));
  const [retry, setRetry] = useState(initial.retry_interval_hours);
  const [hls, setHls] = useState(initial.hls_enabled);
  const [qualityUpgrade, setQualityUpgrade] = useState(initial.quality_upgrade_enabled);
  const [notifyFailed, setNotifyFailed] = useState(initial.notify_failed_enabled);
  const [notifyFrozen, setNotifyFrozen] = useState(initial.notify_frozen_enabled);
  const [channels, setChannels] = useState<NotificationChannel[]>(
    initial.notification_channels ?? [],
  );
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
          notify_failed_enabled: notifyFailed,
          notify_frozen_enabled: notifyFrozen,
          notification_channels: channels,
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

      {/* ── Notifications ───────────────────────────────────────────────── */}
      <div className="space-y-4 rounded-lg border p-4">
        <div>
          <p className="text-sm font-semibold">Notifications</p>
          <p className="text-muted-foreground text-xs">
            Add channels (email, Telegram, ntfy, Discord…) using{" "}
            <a
              className="underline"
              href="https://github.com/caronc/apprise/wiki"
              target="_blank"
              rel="noreferrer"
            >
              Apprise URL syntax
            </a>
            . Toggles below decide which events fire.
          </p>
        </div>
        <div className="flex items-center gap-3 rounded-lg border p-3">
          <Switch id="notifyFailed" checked={notifyFailed} onCheckedChange={setNotifyFailed} />
          <div>
            <Label htmlFor="notifyFailed">Item entered FAILED</Label>
            <p className="text-muted-foreground text-sm">
              Encode failed, library file vanished, or other unrecoverable pipeline error.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-lg border p-3">
          <Switch id="notifyFrozen" checked={notifyFrozen} onCheckedChange={setNotifyFrozen} />
          <div>
            <Label htmlFor="notifyFrozen">Item moved to FROZEN_AS_IS</Label>
            <p className="text-muted-foreground text-sm">
              Audio policy couldn&apos;t be satisfied and the file was accepted as-is.
            </p>
          </div>
        </div>
        <ChannelsEditor value={channels} onChange={setChannels} />
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
