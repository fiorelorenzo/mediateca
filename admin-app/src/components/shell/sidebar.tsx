"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  GitBranch,
  Home,
  Layers,
  Library,
  ScrollText,
  Server,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { Logo } from "@/components/icons/logo";

// Pipeline is a single nav entry that covers every stage sub-page
// (/pipeline/request, /pipeline/acquire, /pipeline/process, /pipeline/available,
// /pipeline/retain, /pipeline/deleted, /pipeline/blocked). Active highlighting
// uses a prefix match on `/pipeline` so any sub-page lights up the entry.
const items = [
  { href: "/", label: "Dashboard", icon: Home, match: "exact" as const },
  { href: "/pipeline", label: "Pipeline", icon: GitBranch, match: "prefix" as const },
  { href: "/library", label: "Library", icon: Library, match: "prefix" as const },
  { href: "/server", label: "Server", icon: Server, match: "prefix" as const },
  { href: "/services", label: "Services", icon: Layers, match: "prefix" as const },
  { href: "/logs", label: "Logs", icon: ScrollText, match: "prefix" as const },
  { href: "/settings", label: "Settings", icon: Settings, match: "prefix" as const },
];

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="bg-muted/30 hidden h-screen w-64 shrink-0 flex-col border-r lg:flex">
      <div className="flex h-14 shrink-0 items-center border-b px-4">
        <Logo size={24} withWordmark />
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {items.map((it) => {
          const Icon = it.icon;
          const active =
            it.match === "exact" ? path === it.href : path === it.href || path.startsWith(`${it.href}/`);
          return (
            <Link
              key={it.href}
              href={it.href}
              className={cn(
                "hover:bg-accent flex items-center gap-3 rounded-md px-3 py-2 text-sm",
                active && "bg-accent font-medium",
              )}
            >
              <Icon className="size-4" />
              {it.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
