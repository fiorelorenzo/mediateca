"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, Trash2, AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DeleteItemPayload } from "@/lib/api/client";
import { arrs, type SonarrEpisode } from "@/lib/api/arrs";
import type { Item } from "@/lib/api/types";

type Mode = "full" | "partial";

export function DeleteDialog({ item }: { item: Item }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const isSeries = item.source === "sonarr";

  const [mode, setMode] = useState<Mode>("full");
  const [deleteFiles, setDeleteFiles] = useState(true);
  const [purgeTorrent, setPurgeTorrent] = useState(true);
  const [unmonitor, setUnmonitor] = useState(true);
  const [confirmText, setConfirmText] = useState("");

  // Per-episode selection (only used when mode=partial). Map episodeId → selected.
  const [selectedEpisodes, setSelectedEpisodes] = useState<Set<number>>(new Set());
  const [expandedSeasons, setExpandedSeasons] = useState<Set<number>>(new Set());

  const seriesId = item.series_id ?? item.source_id;
  const episodes = useQuery({
    queryKey: ["sonarr", "episodes", seriesId],
    queryFn: () => arrs.seriesEpisodes(seriesId),
    enabled: open && isSeries && mode === "partial",
    staleTime: 60_000,
  });

  const seasons = useMemo(() => {
    if (!episodes.data) return [];
    const bySeason = new Map<number, SonarrEpisode[]>();
    for (const ep of episodes.data) {
      const arr = bySeason.get(ep.seasonNumber) ?? [];
      arr.push(ep);
      bySeason.set(ep.seasonNumber, arr);
    }
    return [...bySeason.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([n, eps]) => ({
        n,
        eps: eps.sort((a, b) => a.episodeNumber - b.episodeNumber),
      }));
  }, [episodes.data]);

  function toggleEpisode(id: number) {
    setSelectedEpisodes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSeason(n: number) {
    if (!episodes.data) return;
    const inSeason = episodes.data.filter((e) => e.seasonNumber === n && e.hasFile);
    const ids = inSeason.map((e) => e.id);
    const allSelected = ids.length > 0 && ids.every((id) => selectedEpisodes.has(id));
    setSelectedEpisodes((prev) => {
      const next = new Set(prev);
      if (allSelected) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  function toggleSeasonExpand(n: number) {
    setExpandedSeasons((prev) => {
      const next = new Set(prev);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });
  }

  const titleNeedsTyping = mode === "full" && deleteFiles;
  const confirmOk = !titleNeedsTyping || confirmText.trim() === item.title.trim();
  const partialEmpty = mode === "partial" && selectedEpisodes.size === 0;
  const canSubmit = confirmOk && !partialEmpty;

  const [pending, setPending] = useState(false);

  async function submit() {
    setPending(true);
    try {
      const payload: DeleteItemPayload =
        mode === "full"
          ? { delete_files: deleteFiles, purge_torrent: purgeTorrent }
          : {
              delete_files: true,
              purge_torrent: false,
              episode_ids: [...selectedEpisodes],
              unmonitor,
            };
      const result = await api.deleteItem(item.id, payload);
      if (result.mode === "partial") {
        toast.success(
          `Deleted ${result.files_deleted ?? 0} file${result.files_deleted === 1 ? "" : "s"} (${
            result.episodes_targeted ?? 0
          } episodes)`,
        );
        setOpen(false);
        router.refresh();
      } else {
        toast.success("Title removed from the stack");
        setOpen(false);
        router.push("/library");
      }
    } catch (e) {
      toast.error(`Delete failed: ${(e as Error).message}`);
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) {
          setConfirmText("");
          setSelectedEpisodes(new Set());
          setMode("full");
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="destructive">
          <Trash2 className="mr-1 size-4" />
          Delete
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="text-destructive size-5" />
            Delete {isSeries ? "series" : "movie"}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">
            <span className="text-foreground font-medium">{item.title}</span> — this acts on{" "}
            {item.source} (#{item.source_id}), the active torrent (if any), and the orchestrator
            item DB. Files on disk are unlinked when &apos;Delete files&apos; is on.
          </p>

          {isSeries && (
            <div className="bg-muted/30 inline-flex rounded-md border p-1 text-sm">
              <button
                type="button"
                onClick={() => setMode("full")}
                className={`rounded px-3 py-1.5 transition ${
                  mode === "full"
                    ? "bg-background shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Full series
              </button>
              <button
                type="button"
                onClick={() => setMode("partial")}
                className={`rounded px-3 py-1.5 transition ${
                  mode === "partial"
                    ? "bg-background shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Pick episodes
              </button>
            </div>
          )}

          {mode === "full" ? (
            <div className="space-y-3 rounded-md border p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <Label htmlFor="delete-files" className="text-sm">
                    Delete files from disk
                  </Label>
                  <p className="text-muted-foreground text-xs">
                    Unlinks the {isSeries ? "series" : "movie"} folder under {`/data/media`}.
                  </p>
                </div>
                <Switch id="delete-files" checked={deleteFiles} onCheckedChange={setDeleteFiles} />
              </div>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <Label htmlFor="purge-torrent" className="text-sm">
                    Cancel active download
                  </Label>
                  <p className="text-muted-foreground text-xs">
                    Removes any matching torrent from qBit (with files) before deleting.
                  </p>
                </div>
                <Switch
                  id="purge-torrent"
                  checked={purgeTorrent}
                  onCheckedChange={setPurgeTorrent}
                />
              </div>

              {titleNeedsTyping && (
                <div className="border-destructive/40 bg-destructive/5 space-y-1.5 rounded-md border p-3">
                  <Label htmlFor="confirm-title" className="text-xs">
                    Type the title to confirm:{" "}
                    <span className="text-foreground font-mono font-medium">{item.title}</span>
                  </Label>
                  <Input
                    id="confirm-title"
                    value={confirmText}
                    onChange={(e) => setConfirmText(e.target.value)}
                    placeholder={item.title}
                    className="font-mono text-sm"
                  />
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3 rounded-md border p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <Label htmlFor="unmonitor" className="text-sm">
                    Also unmonitor selected
                  </Label>
                  <p className="text-muted-foreground text-xs">
                    So Sonarr won&apos;t immediately re-grab them on the next RSS sweep.
                  </p>
                </div>
                <Switch id="unmonitor" checked={unmonitor} onCheckedChange={setUnmonitor} />
              </div>

              <div className="-mx-1 max-h-[40vh] overflow-y-auto px-1">
                {episodes.isLoading ? (
                  <div className="space-y-2">
                    {[...Array(3)].map((_, i) => (
                      <Skeleton key={i} className="h-10 w-full" />
                    ))}
                  </div>
                ) : seasons.length === 0 ? (
                  <p className="text-muted-foreground text-sm">No episodes found.</p>
                ) : (
                  <div className="space-y-1">
                    {seasons.map(({ n, eps }) => {
                      const expanded = expandedSeasons.has(n);
                      const withFile = eps.filter((e) => e.hasFile);
                      const selected = withFile.filter((e) => selectedEpisodes.has(e.id)).length;
                      const allSelected = withFile.length > 0 && selected === withFile.length;
                      return (
                        <div key={n} className="rounded-md border">
                          <div className="flex items-center gap-2 px-2 py-1.5">
                            <button
                              type="button"
                              onClick={() => toggleSeasonExpand(n)}
                              className="text-muted-foreground hover:text-foreground"
                              aria-label={expanded ? "Collapse" : "Expand"}
                            >
                              {expanded ? (
                                <ChevronDown className="size-4" />
                              ) : (
                                <ChevronRight className="size-4" />
                              )}
                            </button>
                            <input
                              id={`season-${n}`}
                              type="checkbox"
                              checked={allSelected}
                              ref={(el) => {
                                if (el) el.indeterminate = selected > 0 && !allSelected;
                              }}
                              onChange={() => toggleSeason(n)}
                              disabled={withFile.length === 0}
                              className="size-4"
                            />
                            <label
                              htmlFor={`season-${n}`}
                              className="flex flex-1 cursor-pointer items-center justify-between text-sm"
                            >
                              <span className="font-medium">
                                {n === 0 ? "Specials" : `Season ${n}`}
                              </span>
                              <span className="text-muted-foreground text-xs tabular-nums">
                                {selected}/{withFile.length} selected · {eps.length} ep
                              </span>
                            </label>
                          </div>
                          {expanded && (
                            <div className="border-t">
                              {eps.map((ep) => (
                                <label
                                  key={ep.id}
                                  className="hover:bg-accent/30 flex cursor-pointer items-center gap-2 px-2 py-1 pl-9 text-sm"
                                >
                                  <input
                                    type="checkbox"
                                    checked={selectedEpisodes.has(ep.id)}
                                    onChange={() => toggleEpisode(ep.id)}
                                    disabled={!ep.hasFile}
                                    className="size-4"
                                  />
                                  <span className="text-muted-foreground w-12 font-mono tabular-nums">
                                    {n}x{String(ep.episodeNumber).padStart(2, "0")}
                                  </span>
                                  <span className="flex-1 truncate">{ep.title}</span>
                                  {!ep.hasFile && (
                                    <span className="text-muted-foreground text-[10px] uppercase">
                                      no file
                                    </span>
                                  )}
                                </label>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
              <p className="text-muted-foreground text-xs">
                {selectedEpisodes.size} episode{selectedEpisodes.size === 1 ? "" : "s"} selected.
                Series stays in Sonarr; only the file{selectedEpisodes.size === 1 ? "" : "s"} on
                disk and (if checked) the monitor flag are touched.
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={submit} disabled={!canSubmit || pending}>
            <Trash2 className="mr-1 size-4" />
            {pending
              ? "Deleting…"
              : mode === "full"
                ? "Delete title"
                : `Delete ${selectedEpisodes.size} episode${selectedEpisodes.size === 1 ? "" : "s"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
