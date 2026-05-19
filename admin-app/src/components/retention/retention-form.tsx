"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { retentionApi } from "@/lib/api/retention";
import type { RetentionSettingsPayload } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type FormState = RetentionSettingsPayload;
type FieldError = string | null;

function Section({
  title,
  children,
  open = false,
}: {
  title: string;
  children: React.ReactNode;
  open?: boolean;
}) {
  return (
    <details open={open} className="rounded-md border bg-card">
      <summary className="cursor-pointer select-none px-4 py-2 font-medium">{title}</summary>
      <div className="space-y-3 p-4 pt-2">{children}</div>
    </details>
  );
}

function NumField(props: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  error?: FieldError;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span>{props.label}</span>
      <Input
        type="number"
        value={props.value}
        min={props.min}
        max={props.max}
        onChange={(e) => props.onChange(Number(e.target.value))}
        className="max-w-[160px]"
      />
      {props.error ? <span className="text-xs text-red-500">{props.error}</span> : null}
    </label>
  );
}

function CsvField(props: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span>{props.label}</span>
      <Input
        type="text"
        value={props.value.join(",")}
        placeholder="user-id-1,user-id-2"
        onChange={(e) => {
          const arr = e.target.value
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
          props.onChange(arr);
        }}
        className="max-w-md"
      />
    </label>
  );
}

function validate(s: FormState): Partial<Record<keyof FormState, string>> {
  const errs: Partial<Record<keyof FormState, string>> = {};
  if (s.movie_ttl_days < 1) errs.movie_ttl_days = "Must be ≥ 1";
  if (s.movie_grace_days < 0) errs.movie_grace_days = "Must be ≥ 0";
  if (s.series_ttl_days < 1) errs.series_ttl_days = "Must be ≥ 1";
  if (s.series_grace_days < 0) errs.series_grace_days = "Must be ≥ 0";
  if (s.series_bait_first_n < 0) errs.series_bait_first_n = "Must be ≥ 0";
  if (s.series_lookahead_n < 0 || s.series_lookahead_n > 50)
    errs.series_lookahead_n = "Must be 0..50";
  if (s.series_engagement_window_days < 1)
    errs.series_engagement_window_days = "Must be ≥ 1";
  if (s.disk_pressure_target_free_pct < 1 || s.disk_pressure_target_free_pct > 50)
    errs.disk_pressure_target_free_pct = "Must be 1..50";
  if (s.disk_pressure_critical_free_pct < 1 || s.disk_pressure_critical_free_pct > 50)
    errs.disk_pressure_critical_free_pct = "Must be 1..50";
  return errs;
}

export function RetentionForm() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["retention", "settings"],
    queryFn: retentionApi.getSettings,
    staleTime: 60_000,
  });

  // Draft overlay: local edits layered on top of the server-loaded settings.
  // Avoids the setState-in-effect anti-pattern (lint rule react-hooks/set-state-in-effect)
  // while still letting the form re-sync if the server data changes before any edit.
  const [draft, setDraft] = useState<FormState | null>(null);
  const [saved, setSaved] = useState(false);
  const form: FormState | null = draft ?? data ?? null;

  const save = useMutation({
    mutationFn: (payload: Partial<RetentionSettingsPayload>) => retentionApi.putSettings(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["retention"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  if (isLoading || !form)
    return <div className="text-sm text-muted-foreground">Loading retention settings…</div>;

  const errors = validate(form);
  const hasErrors = Object.keys(errors).length > 0;
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setDraft({ ...form, [k]: v });

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!hasErrors) save.mutate(form);
      }}
    >
      <Section title="Globale" open>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.retention_enabled}
            onChange={(e) => set("retention_enabled", e.target.checked)}
          />
          Abilita retention
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.retention_dry_run}
            onChange={(e) => set("retention_dry_run", e.target.checked)}
          />
          Dry-run (consigliato per la prima settimana)
        </label>
      </Section>

      <Section title="Film">
        <NumField
          label='TTL dopo "visto" (giorni)'
          value={form.movie_ttl_days}
          onChange={(n) => set("movie_ttl_days", n)}
          min={1}
          error={errors.movie_ttl_days}
        />
        <NumField
          label="Grace period (giorni)"
          value={form.movie_grace_days}
          onChange={(n) => set("movie_grace_days", n)}
          min={0}
          error={errors.movie_grace_days}
        />
      </Section>

      <Section title="Serie">
        <NumField
          label='TTL dopo "visto" (giorni)'
          value={form.series_ttl_days}
          onChange={(n) => set("series_ttl_days", n)}
          min={1}
          error={errors.series_ttl_days}
        />
        <NumField
          label="Grace period (giorni)"
          value={form.series_grace_days}
          onChange={(n) => set("series_grace_days", n)}
          min={0}
          error={errors.series_grace_days}
        />
        <NumField
          label="Episodi protetti S01"
          value={form.series_bait_first_n}
          onChange={(n) => set("series_bait_first_n", n)}
          min={0}
          error={errors.series_bait_first_n}
        />
        <NumField
          label="Look-ahead (episodi avanti)"
          value={form.series_lookahead_n}
          onChange={(n) => set("series_lookahead_n", n)}
          min={0}
          max={50}
          error={errors.series_lookahead_n}
        />
        <NumField
          label="Finestra partecipante attivo (giorni)"
          value={form.series_engagement_window_days}
          onChange={(n) => set("series_engagement_window_days", n)}
          min={1}
          error={errors.series_engagement_window_days}
        />
      </Section>

      <Section title="Disk pressure">
        <NumField
          label="Target free space (%)"
          value={form.disk_pressure_target_free_pct}
          onChange={(n) => set("disk_pressure_target_free_pct", n)}
          min={1}
          max={50}
          error={errors.disk_pressure_target_free_pct}
        />
        <NumField
          label="Critical free space (%)"
          value={form.disk_pressure_critical_free_pct}
          onChange={(n) => set("disk_pressure_critical_free_pct", n)}
          min={1}
          max={50}
          error={errors.disk_pressure_critical_free_pct}
        />
        <NumField
          label="Grace ridotto sotto soglia (giorni)"
          value={form.disk_pressure_grace_days}
          onChange={(n) => set("disk_pressure_grace_days", n)}
          min={0}
        />
      </Section>

      <Section title="Partecipanti">
        <CsvField
          label="Include user IDs (vuoto = tutti)"
          value={form.retention_user_ids_include}
          onChange={(v) => set("retention_user_ids_include", v)}
        />
        <CsvField
          label="Exclude user IDs"
          value={form.retention_user_ids_exclude}
          onChange={(v) => set("retention_user_ids_exclude", v)}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.retention_respect_jellyfin_favorites}
            onChange={(e) => set("retention_respect_jellyfin_favorites", e.target.checked)}
          />
          Rispetta Jellyfin Favorites
        </label>
      </Section>

      <Section title="Pin / keep">
        <label className="flex flex-col gap-1 text-sm">
          <span>Tag *arr di immunità</span>
          <Input
            type="text"
            value={form.retention_arr_keep_tag}
            onChange={(e) => set("retention_arr_keep_tag", e.target.value)}
            className="max-w-xs"
          />
        </label>
      </Section>

      <Section title="Circuit breakers">
        <NumField
          label="Max delete/giorno"
          value={form.retention_max_deletes_per_day}
          onChange={(n) => set("retention_max_deletes_per_day", n)}
          min={1}
        />
        <NumField
          label="Max delete/tick"
          value={form.retention_max_deletes_per_tick}
          onChange={(n) => set("retention_max_deletes_per_tick", n)}
          min={1}
        />
      </Section>

      <div className="flex items-center gap-2">
        <Button type="submit" disabled={hasErrors || save.isPending}>
          Salva
        </Button>
        {saved ? <span className="text-xs text-emerald-500">Salvato.</span> : null}
        {save.isError ? <span className="text-xs text-red-500">Errore nel salvataggio.</span> : null}
      </div>
    </form>
  );
}
