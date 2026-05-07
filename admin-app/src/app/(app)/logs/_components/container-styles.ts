// Shared per-container colour palette used by both LogToolbar (selectable
// chips) and LogRow (badges). Keep names in sync with actual container names.

const CONTAINER_PALETTE: Record<
  string,
  { ring: string; dot: string; soft: string; text: string }
> = {
  sonarr: {
    ring: "ring-blue-500",
    dot: "bg-blue-500",
    soft: "bg-blue-500/12 border-blue-500/40",
    text: "text-blue-700 dark:text-blue-300",
  },
  radarr: {
    ring: "ring-amber-500",
    dot: "bg-amber-500",
    soft: "bg-amber-500/12 border-amber-500/40",
    text: "text-amber-700 dark:text-amber-300",
  },
  prowlarr: {
    ring: "ring-orange-500",
    dot: "bg-orange-500",
    soft: "bg-orange-500/12 border-orange-500/40",
    text: "text-orange-700 dark:text-orange-300",
  },
  bazarr: {
    ring: "ring-purple-500",
    dot: "bg-purple-500",
    soft: "bg-purple-500/12 border-purple-500/40",
    text: "text-purple-700 dark:text-purple-300",
  },
  jellyfin: {
    ring: "ring-pink-500",
    dot: "bg-pink-500",
    soft: "bg-pink-500/12 border-pink-500/40",
    text: "text-pink-700 dark:text-pink-300",
  },
  qbittorrent: {
    ring: "ring-cyan-500",
    dot: "bg-cyan-500",
    soft: "bg-cyan-500/12 border-cyan-500/40",
    text: "text-cyan-700 dark:text-cyan-300",
  },
  gluetun: {
    ring: "ring-emerald-500",
    dot: "bg-emerald-500",
    soft: "bg-emerald-500/12 border-emerald-500/40",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  "admin-app": {
    ring: "ring-fuchsia-500",
    dot: "bg-fuchsia-500",
    soft: "bg-fuchsia-500/12 border-fuchsia-500/40",
    text: "text-fuchsia-700 dark:text-fuchsia-300",
  },
  caddy: {
    ring: "ring-zinc-500",
    dot: "bg-zinc-500",
    soft: "bg-zinc-500/12 border-zinc-500/40",
    text: "text-zinc-700 dark:text-zinc-300",
  },
  seerr: {
    ring: "ring-violet-500",
    dot: "bg-violet-500",
    soft: "bg-violet-500/12 border-violet-500/40",
    text: "text-violet-700 dark:text-violet-300",
  },
  "seerr-inject": {
    ring: "ring-violet-400",
    dot: "bg-violet-400",
    soft: "bg-violet-400/12 border-violet-400/40",
    text: "text-violet-700 dark:text-violet-300",
  },
  prosody: {
    ring: "ring-teal-500",
    dot: "bg-teal-500",
    soft: "bg-teal-500/12 border-teal-500/40",
    text: "text-teal-700 dark:text-teal-300",
  },
  recyclarr: {
    ring: "ring-yellow-500",
    dot: "bg-yellow-500",
    soft: "bg-yellow-500/12 border-yellow-500/40",
    text: "text-yellow-700 dark:text-yellow-300",
  },
  ofelia: {
    ring: "ring-slate-500",
    dot: "bg-slate-500",
    soft: "bg-slate-500/12 border-slate-500/40",
    text: "text-slate-700 dark:text-slate-300",
  },
  dispatcharr: {
    ring: "ring-rose-500",
    dot: "bg-rose-500",
    soft: "bg-rose-500/12 border-rose-500/40",
    text: "text-rose-700 dark:text-rose-300",
  },
  "qb-port-manager": {
    ring: "ring-cyan-400",
    dot: "bg-cyan-400",
    soft: "bg-cyan-400/12 border-cyan-400/40",
    text: "text-cyan-700 dark:text-cyan-300",
  },
  headscale: {
    ring: "ring-indigo-500",
    dot: "bg-indigo-500",
    soft: "bg-indigo-500/12 border-indigo-500/40",
    text: "text-indigo-700 dark:text-indigo-300",
  },
  "headscale-init": {
    ring: "ring-indigo-400",
    dot: "bg-indigo-400",
    soft: "bg-indigo-400/12 border-indigo-400/40",
    text: "text-indigo-700 dark:text-indigo-300",
  },
};

const FALLBACK = {
  ring: "ring-muted-foreground",
  dot: "bg-muted-foreground",
  soft: "bg-muted/50 border-border",
  text: "text-muted-foreground",
};

export function containerStyles(name: string) {
  return CONTAINER_PALETTE[name] ?? FALLBACK;
}
