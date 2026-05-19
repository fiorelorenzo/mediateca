import type { Metadata } from "next";
import { ProcessingList } from "./_components/processing-list";

export const metadata: Metadata = { title: "Process" };

export default function ProcessPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Process</h1>
        <p className="text-muted-foreground text-sm">
          Pipeline → Process · Items currently moving through the pipeline —
          analysing the file, merging audio tracks, promoting to the library, or
          HLS-encoding. Once they finish they show up in{" "}
          <span className="font-medium">Library</span>.
        </p>
      </div>
      <ProcessingList />
    </div>
  );
}
