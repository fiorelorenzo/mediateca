import type { Metadata } from "next";
import { ItemsTable } from "./_components/items-table";

export const metadata: Metadata = { title: "Library" };

export default function LibraryPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Library</h1>
        <p className="text-muted-foreground">Items the orchestrator manages.</p>
      </div>
      <ItemsTable />
    </div>
  );
}
