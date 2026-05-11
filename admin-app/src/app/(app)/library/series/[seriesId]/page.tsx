import { notFound } from "next/navigation";

import { SeriesDetail } from "./_components/series-detail";

export default async function SeriesDetailPage(props: {
  params: Promise<{ seriesId: string }>;
}) {
  const seriesId = Number((await props.params).seriesId);
  if (Number.isNaN(seriesId) || seriesId <= 0) notFound();
  return <SeriesDetail seriesId={seriesId} />;
}
