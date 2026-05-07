import type { Metadata } from "next";
import { LogViewer } from "./_components/log-viewer";

export const metadata: Metadata = { title: "Logs" };

export default function LogsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Logs</h1>
        <p className="text-muted-foreground">Real-time stack-wide log streaming.</p>
      </div>
      <LogViewer />
    </div>
  );
}
