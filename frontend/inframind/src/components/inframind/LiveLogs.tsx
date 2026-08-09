import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Dot, Panel, PanelLabel } from "./primitives";
import type { LogEntry } from "@/api/types";

const FILTERS = [
  { key: "monitoring", label: "Monitoring", dot: "bg-agent-monitoring", text: "text-agent-monitoring" },
  { key: "root_cause", label: "Root Cause", dot: "bg-agent-root-cause", text: "text-agent-root-cause" },
  { key: "optimization", label: "Optimization", dot: "bg-agent-optimization", text: "text-agent-optimization" },
  { key: "reporting", label: "Reporting", dot: "bg-agent-reporting", text: "text-agent-reporting" },
] as const;

export function LiveLogs({ logs }: { logs: LogEntry[] }) {
  const [active, setActive] = useState<string[]>(FILTERS.map((f) => f.key));
  const scrollRef = useRef<HTMLDivElement>(null);

  const visible = useMemo(
    () => logs.filter((l) => active.includes(l.agent)),
    [logs, active],
  );

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visible.length]);

  const toggle = (key: string) =>
    setActive((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );

  return (
    <Panel className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PanelLabel>Live logs</PanelLabel>
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => {
            const on = active.includes(f.key);
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => toggle(f.key)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                  on
                    ? "border-border bg-background text-foreground"
                    : "border-transparent bg-transparent text-muted-foreground/60",
                )}
              >
                <Dot className={f.dot} />
                {f.label}
              </button>
            );
          })}
        </div>
      </div>

      <div
        ref={scrollRef}
        className="mt-4 h-72 overflow-y-auto rounded-lg border border-border bg-background p-3 font-mono text-xs leading-6"
      >
        {visible.length === 0 ? (
          <p className="text-muted-foreground/70">Waiting for log stream…</p>
        ) : (
          visible.map((log, i) => {
            const meta = FILTERS.find((f) => f.key === log.agent);
            return (
              <div key={`${log.timestamp}-${i}`} className="flex gap-2">
                <span className="text-muted-foreground/60">{log.timestamp}</span>
                <span className={meta?.text ?? "text-muted-foreground"}>•</span>
                <span className="min-w-0 flex-1 break-words text-foreground/90">
                  {log.message}
                </span>
              </div>
            );
          })
        )}
      </div>
    </Panel>
  );
}