"use client";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const v = document.cookie.match(/theme=(\w+)/)?.[1] ?? "dark";
    setDark(v === "dark");
    document.documentElement.classList.toggle("dark", v === "dark");
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
