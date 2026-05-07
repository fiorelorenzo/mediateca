import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  count?: number;
  className?: string;
}

export function CardsSkeleton({ count = 6, className = "" }: Props) {
  return (
    <div className={`grid gap-4 sm:grid-cols-2 lg:grid-cols-3 ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="space-y-3 rounded-lg border p-6">
          <Skeleton className="h-5 w-2/3" style={{ animationDelay: `${i * 60}ms` }} />
          <Skeleton className="h-4 w-full" style={{ animationDelay: `${i * 60 + 30}ms` }} />
          <Skeleton className="h-4 w-1/2" style={{ animationDelay: `${i * 60 + 60}ms` }} />
        </div>
      ))}
    </div>
  );
}
