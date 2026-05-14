import { notFound } from "next/navigation";

import { SeriesDetail } from "./_components/series-detail";

export default async function SeriesDetailPage(props: {
  params: Promise<{ seriesId: string }>;
}) {
  const seriesId = Number((await props.params).seriesId);
  if (Number.isNaN(seriesId) || seriesId <= 0) notFound();
  const domain = process.env.PUBLIC_DOMAIN ?? "localhost";
  return <SeriesDetail seriesId={seriesId} domain={domain} />;
}
