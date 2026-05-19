"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Cog,
  Download,
  Home,
  Inbox,
  Layers,
  Library,
  ScrollText,
  Server,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { Logo } from "@/components/icons/logo";

const items = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/library", label: "Library", icon: Library },
  { href: "/pipeline/request", label: "Request", icon: Inbox },
  { href: "/pipeline/acquire", label: "Acquire", icon: Download },
  { href: "/pipeline/process", label: "Process", icon: Cog },
  { href: "/server", label: "Server", icon: Server },
  { href: "/services", label: "Services", icon: Layers },
  { href: "/logs", label: "Logs", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
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
          const active = path === it.href || (it.href !== "/" && path.startsWith(it.href));
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
