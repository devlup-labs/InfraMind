import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-lg border border-border bg-card p-5", className)}>
      {children}
    </section>
  );
}

export function PanelLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
      {children}
    </h2>
  );
}

export function Dot({ className }: { className?: string }) {
  return <span className={cn("inline-block size-2 shrink-0 rounded-full", className)} />;
}

export function formatDuration(seconds?: number | null) {
  if (seconds === undefined || seconds === null || Number.isNaN(seconds)) return "--:--";
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}