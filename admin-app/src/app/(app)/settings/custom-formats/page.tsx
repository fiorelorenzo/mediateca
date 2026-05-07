import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { CFEditor } from "./_components/cf-editor";

export const metadata: Metadata = { title: "Custom Formats" };

export default function CFPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Custom Formats</h1>
          <p className="text-muted-foreground">
            Stack-managed custom formats. Pushed to Sonarr &amp; Radarr.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/settings/trash">View TRaSH formats</Link>
        </Button>
      </div>
      <CFEditor />
    </div>
  );
}
