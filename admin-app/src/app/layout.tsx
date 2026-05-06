import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { QueryProvider } from "@/components/providers/query-provider";

export const metadata: Metadata = {
  title: "Mediateca",
  description: "Self-hosted media stack admin",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
