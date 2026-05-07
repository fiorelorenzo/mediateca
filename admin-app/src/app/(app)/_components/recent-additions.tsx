"use client";
import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Film, Sparkles, Tv } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { arrPoster, arrs, type ArrMovie, type ArrSeries } from "@/lib/api/arrs";

interface AdditionRow {
  id: number;
  kind: "movie" | "tv";
  title: string;
  year?: number;
  added: string;
  poster: string | null;
}

export function RecentAdditions() {
  const movies = useQuery({
    queryKey: ["radarr", "movies"],
    queryFn: arrs.allMovies,
    staleTime: 60_000,
  });
  const series = useQuery({
    queryKey: ["sonarr", "series"],
    queryFn: arrs.allSeries,
    staleTime: 60_000,
  });

  const items: AdditionRow[] = useMemo(() => {
    const out: AdditionRow[] = [];
    (movies.data ?? [])
      .filter((m: ArrMovie) => m.hasFile)
      .forEach((m) =>
        out.push({
          id: m.id,
          kind: "movie",
          title: m.title,
          year: m.year,
          added: m.added,
          poster: arrPoster(m.images),
        }),
      );
    (series.data ?? [])
      .filter((s: ArrSeries) => (s.statistics?.episodeFileCount ?? 0) > 0)
      .forEach((s) =>
        out.push({
          id: s.id,
          kind: "tv",
          title: s.title,
          year: s.year,
          added: s.added,
          poster: arrPoster(s.images),
        }),
      );
    return out
      .sort((a, b) => (a.added < b.added ? 1 : -1))
      .slice(0, 8);
  }, [movies.data, series.data]);

  const loading = movies.isLoading || series.isLoading;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="size-4" />
          Recently added
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-4 gap-3 sm:grid-cols-4 md:grid-cols-8">
          {loading
            ? [...Array(8)].map((_, i) => (
                <Skeleton key={i} className="aspect-[2/3] rounded-md" />
              ))
            : items.length === 0
              ? (
                  <div className="text-muted-foreground col-span-full py-4 text-center text-sm">
                    Library is empty.
                  </div>
                )
              : items.map((it, i) => (
                  <motion.div
                    key={`${it.kind}-${it.id}`}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, delay: Math.min(i * 0.03, 0.2) }}
                  >
                    <Link
                      href={it.kind === "movie" ? "/library" : "/library"}
                      className="group block"
                      title={`${it.title}${it.year ? ` (${it.year})` : ""}`}
                    >
                      <div className="bg-muted relative aspect-[2/3] overflow-hidden rounded-md">
                        {it.poster ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={it.poster}
                            alt=""
                            loading="lazy"
                            className="h-full w-full object-cover transition group-hover:scale-105"
                          />
                        ) : (
                          <div className="text-muted-foreground flex h-full items-center justify-center">
                            {it.kind === "movie" ? (
                              <Film className="size-6" />
                            ) : (
                              <Tv className="size-6" />
                            )}
                          </div>
                        )}
                        <div className="bg-black/0 group-hover:bg-black/20 absolute inset-0 transition" />
                      </div>
                      <div className="mt-1.5 truncate text-[11px] font-medium leading-tight">
                        {it.title}
                      </div>
                      <div className="text-muted-foreground truncate text-[10px]">
                        {it.year ?? "—"}
                      </div>
                    </Link>
                  </motion.div>
                ))}
        </div>
      </CardContent>
    </Card>
  );
}
