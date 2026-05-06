import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth/session";

export async function POST() {
  (await cookies()).delete(SESSION_COOKIE);
  return NextResponse.redirect(new URL("/login", process.env.PUBLIC_DOMAIN ? `https://admin.${process.env.PUBLIC_DOMAIN}` : "http://localhost:3000"));
}
