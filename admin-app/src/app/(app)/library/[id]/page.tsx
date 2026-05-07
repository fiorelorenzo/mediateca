import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Check,
  GitMerge,
  AlertCircle,
  Lock,
  Tag,
  Search,
  Inbox,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { orchestrator } from "@/lib/api/orchestrator";
import type { HistoryEvent } from "@/lib/api/types";
import { ItemActions } from "../_components/item-actions";
import { AudioBadges } from "../_components/audio-badges";

// ── HistoryTimeline ──────────────────────────────────────────────────────────

const EVENT_ICON: Record<string, React.ElementType> = {
  PROMOTED: Check,
  MERGED: GitMerge,
  FAILED: AlertCircle,
  MERGE_REJECTED: AlertCircle,
  POLICY_OVERRIDDEN: Lock,
  ANALYZED: Tag,
  SEARCH_TRIGGERED: Search,
  INCOMPLETE: Inbox,
};

const EVENT_COLOR: Record<string, string> = {
  PROMOTED: "text-green-500",
  MERGED: "text-blue-500",
  FAILED: "text-red-500",
  MERGE_REJECTED: "text-red-400",
  POLICY_OVERRIDDEN: "text-amber-500",
  ANALYZED: "text-violet-500",
  SEARCH_TRIGGERED: "text-sky-500",
  INCOMPLETE: "text-muted-foreground",
};

function HistoryTimeline({ history }: { history: HistoryEvent[] }) {
  if (history.length === 0) {
    return <p className="text-muted-foreground text-sm">No events.</p>;
  }

  return (
    <ol className="relative border-l border-border ml-3 space-y-6">
      {history.map((h, i) => {
        const Icon = EVENT_ICON[h.event] ?? AlertCircle;
        const colorClass = EVENT_COLOR[h.event] ?? "text-muted-foreground";

        return (
          <li key={i} className="ml-6">
            {/* Dot on the timeline */}
            <span
              className={`absolute -left-3 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-background ${colorClass}`}
            >
              <Icon className="h-3.5 w-3.5" />
            </span>

            {/* Event name + timestamp */}
            <div className="flex flex-wrap items-center gap-2">
              <span className={`font-mono text-sm font-semibold ${colorClass}`}>
                {h.event}
              </span>
              <time className="text-xs text-muted-foreground">{h.created_at}</time>
            </div>

            {/* Optional JSON detail */}
            {h.detail && Object.keys(h.detail).length > 0 && (
              <pre className="mt-1 rounded bg-muted px-3 py-2 text-xs overflow-x-auto whitespace-pre-wrap break-all">
                {JSON.stringify(h.detail, null, 2)}
              </pre>
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default async function ItemDetail(props: { params: Promise<{ id: string }> }) {
  const id = Number((await props.params).id);
  if (Number.isNaN(id)) notFound();
  let payload;
  try {
    payload = await orchestrator.getItem(id);
  } catch {
    notFound();
  }
  const { item, history } = payload;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/library">← Library</Link>
        </Button>
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">{item.title}</h1>
      <div className="text-sm text-muted-foreground">
        {item.source} · id #{item.source_id} · status: <strong>{item.status}</strong>
        {item.status_reason && ` — ${item.status_reason}`}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Audio</CardTitle>
        </CardHeader>
        <CardContent>
          <AudioBadges present={item.audio_present} required={item.audio_required} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <ItemActions item={item} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
        </CardHeader>
        <CardContent>
          <HistoryTimeline history={history} />
        </CardContent>
      </Card>
    </div>
  );
}
