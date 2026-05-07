"use client";
import { useTransition, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import type { Item } from "@/lib/api/types";

export function ItemActions({ item }: { item: Item }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const refresh = () => router.refresh();

  return (
    <div className="flex flex-wrap gap-2">
      <Button
        disabled={pending}
        variant="default"
        onClick={() =>
          start(async () => {
            try {
              await api.searchNow(item.id);
              toast.success("Search triggered successfully.");
              refresh();
            } catch {
              toast.error("Failed to trigger search.");
            }
          })
        }
      >
        Search now
      </Button>
      <Button
        disabled={pending}
        variant="outline"
        onClick={() =>
          start(async () => {
            try {
              await api.acceptAsIs(item.id);
              toast.success("Item accepted as-is.");
              refresh();
            } catch {
              toast.error("Failed to accept item as-is.");
            }
          })
        }
      >
        Accept as-is
      </Button>
      <OverrideDialog item={item} onSaved={refresh} />
    </div>
  );
}

function OverrideDialog({ item, onSaved }: { item: Item; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [langs, setLangs] = useState((item.audio_required ?? []).join(","));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary">Override policy</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Per-item language policy</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="langs">
            Required audio languages (comma-separated, supports `@original`)
          </Label>
          <Input
            id="langs"
            value={langs}
            onChange={(e) => setLangs(e.target.value)}
            placeholder="ita, @original"
          />
          <p className="text-muted-foreground text-sm">Leave empty to clear the override.</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
          <Button
            onClick={() =>
              start(async () => {
                const list = langs
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean);
                try {
                  await api.overridePolicy(item.id, list.length === 0 ? null : list);
                  toast.success("Policy override saved.");
                  setOpen(false);
                  onSaved();
                } catch {
                  toast.error("Failed to save policy override.");
                }
              })
            }
            disabled={pending}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
