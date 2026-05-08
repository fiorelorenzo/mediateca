import { Button } from "@/components/ui/button";
import { ThemeToggle } from "./theme-toggle";
import { LogOut } from "lucide-react";

export function Header() {
  return (
    <header className="bg-background/80 flex h-14 shrink-0 items-center justify-end gap-2 border-b px-4 backdrop-blur">
      <ThemeToggle />
      <form action="/api/logout" method="POST">
        <Button variant="ghost" size="icon" type="submit" aria-label="Logout">
          <LogOut className="size-4" />
        </Button>
      </form>
    </header>
  );
}
