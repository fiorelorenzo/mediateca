"use client";

import { motion } from "motion/react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/**
 * Lightweight enter-only fade between routes.
 *
 * Previously this used `<AnimatePresence mode="wait">` which sequenced
 * out → (gap) → in, so during the gap both the old and the new page
 * were at opacity 0 — a visible "blank" flash, especially noticeable on
 * pages that also need to fetch data on mount (you see: old page fades
 * out, blank, then the in animation kicks in once data arrives).
 *
 * A single motion.div keyed by pathname lets the new page's enter run
 * as soon as Next.js mounts it; the previous tree is unmounted with no
 * exit animation, so there's no gap. Duration kept short so navigation
 * still feels intentional but never blocked.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <motion.div
      key={pathname}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.12, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
