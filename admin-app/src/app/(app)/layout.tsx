import type { ReactNode } from "react";
import { Sidebar } from "@/components/shell/sidebar";
import { Header } from "@/components/shell/header";
import { PageTransition } from "@/components/page-transition";
import { CommandPalette } from "@/components/command-palette";

export default function AppLayout({ children }: { children: ReactNode }) {
  // h-screen + overflow-hidden on the shell pins both Sidebar and Header.
  // Only the <main> region scrolls. Was min-h-screen before, which let the
  // body grow taller than the viewport once content exceeded it — pulling
  // the chrome along with the scroll.
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
          <PageTransition>{children}</PageTransition>
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}
