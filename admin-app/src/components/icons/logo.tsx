// admin-app/src/components/icons/logo.tsx
import { cn } from "@/lib/utils/cn";
import { LogoMark } from "./logo-mark";

interface Props {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}

export function Logo({ size = 24, withWordmark = false, className }: Props) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark size={size} className="text-primary" />
      {withWordmark && (
        <span
          className="font-bold tracking-tight"
          style={{ fontSize: size * 0.85, letterSpacing: "-0.02em" }}
        >
          mediateca
        </span>
      )}
    </span>
  );
}
