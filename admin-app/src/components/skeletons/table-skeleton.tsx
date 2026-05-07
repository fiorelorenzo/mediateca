import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  rows?: number;
  columns?: number;
}

export function TableSkeleton({ rows = 8, columns = 4 }: Props) {
  return (
    <div className="rounded-md border">
      <div className="bg-muted/40 border-b p-3">
        <div className="flex gap-4">
          {Array.from({ length: columns }).map((_, i) => (
            <Skeleton key={i} className="h-4 flex-1" />
          ))}
        </div>
      </div>
      <div className="divide-y">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 p-3">
            {Array.from({ length: columns }).map((_, j) => (
              <Skeleton key={j} className="h-4 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
