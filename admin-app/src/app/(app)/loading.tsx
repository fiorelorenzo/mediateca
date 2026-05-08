// Generic suspense fallback for any (app)-segment route that has to
// await on the server (currently /services and /library/[id]). Without
// this, navigation to those routes blocks at the previous page's last
// frame until the await resolves — feels like the UI froze.
//
// We render the same outer shell the destination page will use (heading
// placeholder + a few cards / table skeleton) so the layout doesn't
// jump when the real content swaps in.
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-4 w-72" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="h-[420px] w-full" />
    </div>
  );
}
