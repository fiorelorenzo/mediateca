import { NextRequest, NextResponse } from "next/server";

const ORCH = process.env.ORCHESTRATOR_URL!;
const TOKEN = process.env.ORCHESTRATOR_API_TOKEN!;

async function forward(req: NextRequest, path: string[]): Promise<NextResponse> {
  const target = `${ORCH.replace(/\/$/, "")}/${path.join("/")}${req.nextUrl.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: {
      Accept: req.headers.get("accept") ?? "application/json",
      "Content-Type": req.headers.get("content-type") ?? "application/json",
      Authorization: `Bearer ${TOKEN}`,
    },
    body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
  };
  const upstream = await fetch(target, init);
  const headers = new Headers();
  upstream.headers.forEach((v, k) => {
    if (k !== "transfer-encoding" && k !== "connection") headers.set(k, v);
  });
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
