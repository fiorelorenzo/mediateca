"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Home,
  Library,
  Inbox,
  Download,
  Server,
  Layers,
  Settings,
  ScrollText,
  RefreshCw,
  Moon,
} from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { toast } from "sonner";

const PAGES = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/library", label: "Library", icon: Library },
  { href: "/pipeline/request", label: "Request", icon: Inbox },
  { href: "/pipeline/acquire", label: "Acquire", icon: Download },
  { href: "/server", label: "Server", icon: Server },
  { href: "/services", label: "Services", icon: Layers },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/logs", label: "Logs", icon: ScrollText },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const sync = useMutation({
    mutationFn: api.recyclarrSync,
    onSuccess: () => toast.success("Recyclarr sync started"),
    onError: () => toast.error("Recyclarr sync failed"),
  });

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Type a command or search…" />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Navigation">
          {PAGES.map((p) => (
            <CommandItem key={p.href} onSelect={() => go(p.href)}>
              <p.icon className="mr-2 size-4" />
              {p.label}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Actions">
          <CommandItem
            onSelect={() => {
              setOpen(false);
              sync.mutate();
            }}
          >
            <RefreshCw className="mr-2 size-4" />
            Recyclarr sync now
          </CommandItem>
          <CommandItem
            onSelect={() => {
              const html = document.documentElement;
              const next = html.classList.contains("dark") ? "light" : "dark";
              html.classList.toggle("dark", next === "dark");
              document.cookie = `theme=${next}; path=/; max-age=${60 * 60 * 24 * 365}`;
              setOpen(false);
            }}
          >
            <Moon className="mr-2 size-4" />
            Toggle theme
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
