"use client";

import { useEffect, useRef } from "react";
import { useMotionValue, useTransform, animate, motion } from "motion/react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface StatCardProps {
  title: string;
  value: number;
  color: string;
  delta?: number; // positive = up, negative = down
}

function AnimatedNumber({ value }: { value: number }) {
  const motionValue = useMotionValue(0);
  const rounded = useTransform(motionValue, (v) => Math.round(v));
  const displayRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const ctrl = animate(motionValue, value, { duration: 0.8, ease: "easeOut" });
    return ctrl.stop;
  }, [motionValue, value]);

  useEffect(() => {
    const unsub = rounded.on("change", (v) => {
      if (displayRef.current) displayRef.current.textContent = String(v);
    });
    return unsub;
  }, [rounded]);

  return <span ref={displayRef}>{value}</span>;
}

export function StatCard({ title, value, color, delta }: StatCardProps) {
  const hasDelta = delta !== undefined && delta !== 0;
  const isUp = (delta ?? 0) > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
          <span className={`size-2 rounded-full ${color}`} />
        </CardHeader>
        <CardContent className="flex items-end justify-between">
          <div className="text-3xl font-bold tabular-nums">
            <AnimatedNumber value={value} />
          </div>
          {hasDelta && (
            <span
              className={`mb-0.5 rounded px-1.5 py-0.5 text-xs font-semibold ${
                isUp
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400"
                  : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
              }`}
            >
              {isUp ? "+" : ""}
              {delta}
            </span>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
