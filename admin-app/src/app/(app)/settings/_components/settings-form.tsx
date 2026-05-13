"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Bell,
  Check,
  Eye,
  EyeOff,
  GitMerge,
  Plus,
  Send,
  Sliders,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api/client";
import type { NotificationChannel, Settings } from "@/lib/api/types";

interface FormProps {
  initial: Settings;
}

function maskUrl(url: string): string {
  return url
    .replace(/(:\/\/[^:/@]+:)([^@]+)(@)/, (_m, a, _b, c) => `${a}••••${c}`)
    .replace(/(\/)([A-Za-z0-9_-]{20,})/g, (_m, a) => `${a}••••`);
}

function FieldRow({
  label,
  description,
  children,
  htmlFor,
}: {
  label: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-[1fr_minmax(0,16rem)] sm:items-start sm:gap-6">
      <div className="space-y-1">
        <Label htmlFor={htmlFor} className="text-sm font-medium">
          {label}
        </Label>
        {description && (
          <p className="text-muted-foreground text-sm leading-snug">{description}</p>
        )}
      </div>
      <div className="sm:justify-self-end">{children}</div>
    </div>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onCheckedChange,
  id,
}: {
  label: string;
  description?: React.ReactNode;
  checked: boolean;
  onCheckedChange: (b: boolean) => void;
  id: string;
}) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="space-y-1">
        <Label htmlFor={id} className="text-sm font-medium">
          {label}
        </Label>
        {description && (
          <p className="text-muted-foreground text-sm leading-snug">{description}</p>
        )}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
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
      {value.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed p-4 text-center text-sm">
          No channels yet. Add one below to start receiving notifications.
        </p>
      ) : (
        value.map((c, i) => (
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
            <div className="flex items-center gap-1.5">
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
        ))
      )}
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
        Use the paper-plane button to verify a channel. Changes save with the rest of the form.
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
  const [autoScan, setAutoScan] = useState(initial.auto_scan_on_promote);
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
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (offsetError) {
          toast.error(offsetError);
          return;
        }
        save.mutate({
          required_audio_langs: langs
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          retry_interval_hours: Number(retry),
          accept_as_is_after_attempts: Number(acceptAfter),
          hls_enabled: hls,
          quality_upgrade_enabled: qualityUpgrade,
          auto_scan_on_promote: autoScan,
          notify_failed_enabled: notifyFailed,
          notify_frozen_enabled: notifyFrozen,
          notification_channels: channels,
          merge_duration_reject_threshold_s: Number(durationThreshold),
          merge_offset_safe_ms: Number(offsetSafe),
          merge_offset_reject_ms: Number(offsetReject),
        });
      }}
    >
      <Tabs defaultValue="pipeline" className="space-y-6">
        <TabsList className="grid w-full grid-cols-3 sm:inline-grid sm:w-auto">
          <TabsTrigger value="pipeline" className="gap-2">
            <Sliders className="size-4" />
            <span>Pipeline</span>
          </TabsTrigger>
          <TabsTrigger value="merge" className="gap-2">
            <GitMerge className="size-4" />
            <span>Merge safety</span>
          </TabsTrigger>
          <TabsTrigger value="notifications" className="gap-2">
            <Bell className="size-4" />
            <span>Notifications</span>
          </TabsTrigger>
        </TabsList>

        {/* ── PIPELINE ───────────────────────────────────────────────────── */}
        <TabsContent value="pipeline" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Audio policy</CardTitle>
              <CardDescription>
                Required audio languages drive whether an import is promoted directly or held
                for merge.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <FieldRow
                label="Required audio languages"
                htmlFor="langs"
                description={
                  <>
                    ISO-639-2 codes, comma-separated. <code>@original</code> resolves per-item.
                  </>
                }
              >
                <Input
                  id="langs"
                  value={langs}
                  onChange={(e) => setLangs(e.target.value)}
                  placeholder="ita, @original"
                  className="sm:w-64"
                />
              </FieldRow>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Retry &amp; auto-freeze</CardTitle>
              <CardDescription>
                When an item stays INCOMPLETE the orchestrator re-searches periodically. After N
                attempts it can give up and promote the file as-is.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <FieldRow
                label="Retry interval (hours)"
                htmlFor="retry"
                description="How often catch-up searches run for INCOMPLETE items."
              >
                <Input
                  id="retry"
                  type="number"
                  min={1}
                  value={retry}
                  onChange={(e) => setRetry(Number(e.target.value))}
                  className="sm:w-32"
                />
              </FieldRow>
              <FieldRow
                label="Auto-freeze after N retries"
                htmlFor="acceptAfter"
                description="Set to 0 to never auto-freeze. The item must be promoted manually."
              >
                <Input
                  id="acceptAfter"
                  type="number"
                  min={0}
                  value={acceptAfter}
                  onChange={(e) => setAcceptAfter(Number(e.target.value))}
                  className="sm:w-32"
                />
              </FieldRow>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Encoding &amp; upgrades</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <ToggleRow
                id="hls"
                label="HLS encoding"
                description="When off, files are promoted as-is. Container must be running."
                checked={hls}
                onCheckedChange={setHls}
              />
              <ToggleRow
                id="qualityUpgrade"
                label="Quality upgrades on PROMOTED items"
                description="When on, Sonarr/Radarr keep monitoring after a promote and any better release that comes later replaces the file in place, as long as the new audio is a superset. Off by default — 4K Remux churn can be expensive."
                checked={qualityUpgrade}
                onCheckedChange={setQualityUpgrade}
              />
              <ToggleRow
                id="autoScan"
                label="Trigger Jellyfin + Seerr scans on promote"
                description="Nudge Jellyfin to rescan the library and Seerr to sync recently-added the instant a file lands, instead of waiting for their scheduled jobs."
                checked={autoScan}
                onCheckedChange={setAutoScan}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── MERGE SAFETY ───────────────────────────────────────────────── */}
        <TabsContent value="merge" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Duration &amp; offset thresholds</CardTitle>
              <CardDescription>
                Guard rails for mkvmerge — mismatched files are rejected before they corrupt the
                library copy.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <FieldRow
                label="Duration reject threshold (seconds)"
                htmlFor="durationThreshold"
                description="Merge is rejected if the two files differ in total duration by more than this value."
              >
                <Input
                  id="durationThreshold"
                  type="number"
                  min={0.1}
                  step={0.5}
                  value={durationThreshold}
                  onChange={(e) => setDurationThreshold(Number(e.target.value))}
                  className="sm:w-32"
                />
              </FieldRow>
              <FieldRow
                label="Audio offset safe limit (ms)"
                htmlFor="offsetSafe"
                description="Tracks are considered perfectly aligned when the detected offset is below this value."
              >
                <Input
                  id="offsetSafe"
                  type="number"
                  min={0}
                  step={10}
                  value={offsetSafe}
                  onChange={(e) => setOffsetSafe(Number(e.target.value))}
                  className="sm:w-32"
                />
              </FieldRow>
              <FieldRow
                label="Audio offset reject threshold (ms)"
                htmlFor="offsetReject"
                description={
                  <>
                    Merge is rejected when the detected audio drift exceeds this value (must
                    be &gt; safe limit).
                    {offsetError && (
                      <span className="text-destructive mt-1 block">{offsetError}</span>
                    )}
                  </>
                }
              >
                <Input
                  id="offsetReject"
                  type="number"
                  min={1}
                  step={100}
                  value={offsetReject}
                  onChange={(e) => setOffsetReject(Number(e.target.value))}
                  className="sm:w-32"
                  aria-invalid={!!offsetError}
                />
              </FieldRow>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── NOTIFICATIONS ──────────────────────────────────────────────── */}
        <TabsContent value="notifications" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Events</CardTitle>
              <CardDescription>Which orchestrator events fire a notification.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <ToggleRow
                id="notifyFailed"
                label="Item entered FAILED"
                description="Encode failed, library file vanished, or other unrecoverable pipeline error."
                checked={notifyFailed}
                onCheckedChange={setNotifyFailed}
              />
              <ToggleRow
                id="notifyFrozen"
                label="Item moved to FROZEN_AS_IS"
                description="Audio policy could not be satisfied and the file was accepted as-is."
                checked={notifyFrozen}
                onCheckedChange={setNotifyFrozen}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Channels</CardTitle>
              <CardDescription>
                Add as many channels as you want. URL syntax follows{" "}
                <a
                  className="underline"
                  href="https://github.com/caronc/apprise/wiki"
                  target="_blank"
                  rel="noreferrer"
                >
                  Apprise
                </a>
                : email, Telegram, ntfy, Discord, Pushover, and 100+ more.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChannelsEditor value={channels} onChange={setChannels} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <div className="bg-background sticky bottom-0 z-10 -mx-4 -mb-6 flex items-center justify-end gap-3 border-t px-4 py-3 sm:-mx-6 sm:px-6">
        {offsetError && (
          <p className="text-destructive mr-auto text-sm">Fix errors before saving.</p>
        )}
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
      </div>
    </form>
  );
}

export function SettingsForm() {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });

  if (!data) return null;

  return <SettingsFormInner key={data.required_audio_langs.join(",")} initial={data} />;
}
