// admin-app/src/components/empty-state.tsx
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils/cn";

interface Props {
  icon: LucideIcon;
  title: string;
  description?: string;
  ctaLabel?: string;
  onCta?: () => void;
  className?: string;
}

export function EmptyState({ icon: Icon, title, description, ctaLabel, onCta, className }: Props) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed p-10 text-center",
        className,
      )}
    >
      <div className="bg-muted mb-4 rounded-full p-3">
        <Icon className="text-muted-foreground size-6" />
      </div>
      <h3 className="text-lg font-semibold">{title}</h3>
      {description && <p className="text-muted-foreground mt-1 max-w-sm text-sm">{description}</p>}
      {ctaLabel && onCta && (
        <Button onClick={onCta} className="mt-5">
          {ctaLabel}
        </Button>
      )}
    </div>
  );
}
