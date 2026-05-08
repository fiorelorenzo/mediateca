import "./globals.css";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { QueryProvider } from "@/components/providers/query-provider";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: { default: "Mediateca", template: "%s · Mediateca" },
  description: "Self-hosted media stack admin",
  openGraph: { type: "website", siteName: "Mediateca" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
  ],
};

// Inline blocking script that applies the `dark` class on <html> before any
// CSS evaluates. Without this, SSR ships <html> without the class, the page
// briefly renders light, and the ThemeToggle's useState ends up out of
// sync with the DOM — so the first click "does nothing" (it's just
// bringing the React state and the DOM class back into agreement, no
// visible change) and only the second click actually toggles the theme.
const themeBootstrap = `
  (function(){
    try {
      var m = document.cookie.match(/(?:^|; )theme=(\\w+)/);
      var dark = !m || m[1] === 'dark';
      if (dark) document.documentElement.classList.add('dark');
    } catch (e) {}
  })();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body>
        <QueryProvider>
          {children}
          <Toaster />
        </QueryProvider>
      </body>
    </html>
  );
}
