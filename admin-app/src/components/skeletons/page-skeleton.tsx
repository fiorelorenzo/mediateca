import { TableSkeleton } from "./table-skeleton";
import { CardsSkeleton } from "./cards-skeleton";
import { FormSkeleton } from "./form-skeleton";
import { DetailSkeleton } from "./detail-skeleton";

type Variant = "table" | "cards" | "form" | "detail";

export function PageSkeleton({ variant }: { variant: Variant }) {
  if (variant === "table") return <TableSkeleton />;
  if (variant === "cards") return <CardsSkeleton />;
  if (variant === "form") return <FormSkeleton />;
  if (variant === "detail") return <DetailSkeleton />;
  return null;
}
