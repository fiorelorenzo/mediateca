import { NextRequest, NextResponse } from "next/server";

async function forward(req: NextRequest, path: string[]): Promise<NextResponse> {
  const url = `${process.env.SEERR_URL!.replace(/\/$/, "")}/api/v1/${path.join("/")}${req.nextUrl.search}`;
  const upstream = await fetch(url, {
    method: req.method,
    headers: {
      "X-Api-Key": process.env.SEERR_API_KEY ?? "",
      "Content-Type": req.headers.get("content-type") ?? "application/json",
      Accept: "application/json",
    },
    body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
  });
  const headers = new Headers();
  upstream.headers.forEach((v, k) => {
    if (k !== "transfer-encoding") headers.set(k, v);
  });
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
