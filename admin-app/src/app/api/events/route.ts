import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const upstream = await fetch(`${process.env.ORCHESTRATOR_URL!.replace(/\/$/, "")}/events`, {
    headers: {
      Authorization: `Bearer ${process.env.ORCHESTRATOR_API_TOKEN!}`,
      Accept: "text/event-stream",
    },
  });
  if (!upstream.ok || !upstream.body) {
    return new NextResponse("upstream unavailable", { status: 502 });
  }
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
