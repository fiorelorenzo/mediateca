import { Skeleton } from "@/components/ui/skeleton";

export function FormSkeleton({ fields = 5 }: { fields?: number }) {
  return (
    <div className="max-w-xl space-y-6">
      {Array.from({ length: fields }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-3 w-2/3 opacity-60" />
        </div>
      ))}
      <Skeleton className="h-10 w-24" />
    </div>
  );
}
