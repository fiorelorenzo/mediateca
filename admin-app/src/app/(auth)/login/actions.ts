"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { verifyPassword } from "@/lib/auth/password";
import { SESSION_COOKIE, signSession } from "@/lib/auth/session";

const Schema = z.object({ password: z.string().min(1) });

export async function login(formData: FormData): Promise<void> {
  const parsed = Schema.safeParse({ password: formData.get("password") });
  if (!parsed.success) redirect("/login?error=missing");

  const hash = process.env.ADMIN_PASSWORD_HASH;
  const secret = process.env.ADMIN_SESSION_SECRET;
  if (!hash || !secret) {
    throw new Error("ADMIN_PASSWORD_HASH and ADMIN_SESSION_SECRET must be set");
  }
  if (!(await verifyPassword(parsed.data.password, hash))) {
    redirect("/login?error=invalid");
  }
  const token = await signSession(
    { sub: "admin", iat: Math.floor(Date.now() / 1000) },
    secret,
  );
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  redirect("/");
}
