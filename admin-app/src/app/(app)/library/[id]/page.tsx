import { notFound } from "next/navigation";

import { orchestrator } from "@/lib/api/orchestrator";
import { ItemDetail } from "./_components/item-detail";

export default async function ItemDetailPage(props: { params: Promise<{ id: string }> }) {
  const id = Number((await props.params).id);
  if (Number.isNaN(id)) notFound();
  let payload;
  try {
    payload = await orchestrator.getItem(id);
  } catch {
    notFound();
  }
  const domain = process.env.PUBLIC_DOMAIN ?? "localhost";
  return <ItemDetail item={payload.item} history={payload.history} domain={domain} />;
}
