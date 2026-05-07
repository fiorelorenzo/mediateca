"use client";

import { Button } from "@/components/ui/button";
import { AlertTriangle, RotateCw } from "lucide-react";

interface Props {
  error: Error & { digest?: string };
  reset: () => void;
}

export function ErrorBoundary({ error, reset }: Props) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="bg-destructive/10 mb-4 rounded-full p-3">
        <AlertTriangle className="text-destructive size-6" />
      </div>
      <h2 className="text-2xl font-semibold">Something broke</h2>
      <p className="text-muted-foreground mt-2 max-w-md text-sm">
        {error.message || "An unexpected error occurred."}
      </p>
      {error.digest && (
        <p className="text-muted-foreground/60 mt-1 font-mono text-xs">ref: {error.digest}</p>
      )}
      <Button onClick={reset} className="mt-5" variant="outline">
        <RotateCw className="mr-2 size-4" />
        Try again
      </Button>
    </div>
  );
}
