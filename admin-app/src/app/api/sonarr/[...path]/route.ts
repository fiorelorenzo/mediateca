import { NextRequest, NextResponse } from "next/server";

async function forward(req: NextRequest, path: string[]): Promise<NextResponse> {
  const url = `${process.env.SONARR_URL!.replace(/\/$/, "")}/api/v3/${path.join("/")}${req.nextUrl.search}`;
  const upstream = await fetch(url, {
    method: req.method,
    headers: {
      "X-Api-Key": process.env.SONARR_API_KEY ?? "",
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
  });
  return new NextResponse(upstream.body, { status: upstream.status });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
