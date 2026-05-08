"use client";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

/**
 * Initial state must agree with what the inline `themeBootstrap` script in
 * the root layout applied to <html> — otherwise the first click only
 * resyncs React state with the DOM class and looks like a no-op. We read
 * `documentElement.classList` instead of the cookie because the bootstrap
 * script is the actual source of truth (it might pick a different default
 * on a parse error).
 */
function readDomTheme(): boolean {
  if (typeof document === "undefined") return true;
  return document.documentElement.classList.contains("dark");
}

export function ThemeToggle() {
  const [dark, setDark] = useState<boolean>(readDomTheme);

  // After hydration, double-check we agree with the DOM. This covers the
  // narrow case where SSR rendered with no cookie present and the
  // bootstrap script picked a default that disagrees with our useState
  // initial guess. set-state-in-effect is intentional here: the DOM is
  // the authority post-hydration, not the SSR-time guess.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    document.cookie = `theme=${next ? "dark" : "light"}; path=/; max-age=${60 * 60 * 24 * 365}`;
  }
  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
