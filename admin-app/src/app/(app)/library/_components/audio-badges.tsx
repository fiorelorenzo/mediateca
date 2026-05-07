import { Badge } from "@/components/ui/badge";

export function AudioBadges({
  present,
  required,
}: {
  present: string[];
  required: string[] | null;
}) {
  const missing = (required ?? []).filter((r) => !present.includes(r) && r !== "@original");
  return (
    <div className="flex flex-wrap gap-1">
      {present.map((p) => (
        <Badge key={`p-${p}`} variant="secondary" className="font-mono text-xs">
          {p}
        </Badge>
      ))}
      {missing.map((m) => (
        <Badge key={`m-${m}`} variant="destructive" className="font-mono text-xs opacity-80">
          {m}?
        </Badge>
      ))}
      {present.length === 0 && <span className="text-muted-foreground text-xs">unknown</span>}
    </div>
  );
}
