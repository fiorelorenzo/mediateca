// admin-app/src/components/icons/logo-mark.tsx
import { cn } from "@/lib/utils/cn";

type Variant = "stacked" | "ring" | "geometric-m";

interface Props {
  size?: number;
  variant?: Variant;
  className?: string;
}

export function LogoMark({ size = 24, variant = "stacked", className }: Props) {
  if (variant === "ring") {
    return (
      <svg width={size} height={size} viewBox="0 0 32 32" className={cn(className)} fill="none">
        <circle cx="16" cy="16" r="14" stroke="currentColor" strokeWidth="2.5" />
        <path d="M14 11l8 5-8 5z" fill="currentColor" />
      </svg>
    );
  }
  if (variant === "geometric-m") {
    return (
      <svg width={size} height={size} viewBox="0 0 32 32" className={cn(className)} fill="none">
        <path d="M4 26V6h4l8 12 8-12h4v20h-4V13l-6 9h-4l-6-9v13z" fill="currentColor" />
      </svg>
    );
  }
  // stacked (default)
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={cn(className)}
      fill="currentColor"
    >
      <rect x="2" y="20" width="28" height="6" rx="1.5" opacity="0.45" />
      <rect x="4" y="13" width="24" height="6" rx="1.5" opacity="0.7" />
      <rect x="6" y="6" width="20" height="6" rx="1.5" opacity="1" />
    </svg>
  );
}
