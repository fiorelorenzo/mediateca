"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Library, Server, Layers, Download, Settings, Inbox, Wrench, Home } from "lucide-react";
import { cn } from "@/lib/utils/cn";

const items = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/library", label: "Library", icon: Library },
  { href: "/requests", label: "Requests", icon: Inbox },
  { href: "/downloads", label: "Downloads", icon: Download },
  { href: "/server", label: "Server", icon: Server },
  { href: "/services", label: "Services", icon: Layers },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="hidden w-64 shrink-0 border-r bg-muted/30 lg:block">
      <div className="flex h-14 items-center border-b px-4">
        <span className="text-lg font-semibold">Mediateca</span>
      </div>
      <nav className="space-y-1 p-2">
        {items.map((it) => {
          const Icon = it.icon;
          const active = path === it.href || (it.href !== "/" && path.startsWith(it.href));
          return (
            <Link key={it.href} href={it.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm hover:bg-accent",
                active && "bg-accent font-medium"
              )}>
              <Icon className="size-4" />
              {it.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
