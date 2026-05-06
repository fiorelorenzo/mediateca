import Link from "next/link";
import { notFound } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { orchestrator } from "@/lib/api/orchestrator";
import { ItemActions } from "../_components/item-actions";
import { AudioBadges } from "../_components/audio-badges";

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
          {history.length === 0 ? (
            <p className="text-muted-foreground">No events.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {history.map((h, i) => (
                <li key={i} className="flex justify-between gap-4 border-b pb-2 last:border-0">
                  <span className="font-mono">{h.event}</span>
                  <span className="text-muted-foreground">{h.created_at}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
