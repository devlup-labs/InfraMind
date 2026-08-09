import { Check, ChevronRight, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Dot, Panel, PanelLabel, formatDuration } from "./primitives";
import type { AgentKey, AgentState, PipelineStatus as PipelineStatusData } from "@/api/types";

const AGENTS: { key: AgentKey; name: string }[] = [
  { key: "monitoring", name: "Monitoring Agent" },
  { key: "root_cause", name: "Root Cause Agent" },
  { key: "optimization", name: "Optimization Agent" },
  { key: "reporting", name: "Reporting Agent" },
];

function StatusMark({ state }: { state: AgentState }) {
  switch (state.status) {
    case "completed":
      return (
        <span className="flex items-center gap-2 text-sm font-medium text-success">
          <Check className="size-4" /> Completed
        </span>
      );
    case "running":
      return (
        <span className="flex items-center gap-2 text-sm font-medium text-primary">
          <Loader2 className="size-4 animate-spin" /> Running
        </span>
      );
    case "failed":
      return (
        <span className="flex items-center gap-2 text-sm font-medium text-destructive">
          <X className="size-4" /> Failed
        </span>
      );
    default:
      return (
        <span className="flex items-center gap-2 text-sm font-medium text-idle">
          <Dot className="bg-idle" /> Standby
        </span>
      );
  }
}

export function PipelineStatusPanel({ data }: { data: PipelineStatusData | null }) {
  const agents = data?.agents;
  const activeIndex = (() => {
    if (!agents) return -1;
    const running = AGENTS.findIndex((a) => agents[a.key]?.status === "running");
    if (running !== -1) return running;
    let last = -1;
    AGENTS.forEach((a, i) => {
      const s = agents[a.key]?.status;
      if (s === "completed" || s === "failed") last = i;
    });
    return last;
  })();

  const anomaly = data?.anomaly_detected ?? false;

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <PanelLabel>Suspect metric</PanelLabel>
          <p className="mt-1 font-mono text-lg font-semibold text-foreground">
            {data?.suspect_metric ?? "none"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
              anomaly
                ? "border-destructive/40 bg-destructive/10 text-destructive"
                : "border-success/30 bg-success/10 text-success",
            )}
          >
            <Dot className={anomaly ? "bg-destructive" : "bg-success"} />
            {anomaly ? "Anomaly detected" : "No anomaly"}
          </span>
          <span className="font-mono text-sm text-muted-foreground">
            {formatDuration(data?.elapsed_seconds)}
          </span>
        </div>
      </div>

      <div className="mt-5 flex items-stretch gap-1">
        {AGENTS.map((agent, i) => {
          const state: AgentState = agents?.[agent.key] ?? { status: "standby" };
          const highlighted = i === activeIndex;
          return (
            <div key={agent.key} className="flex flex-1 items-center gap-1">
              <div
                className={cn(
                  "min-w-0 flex-1 rounded-lg border p-4 transition-colors",
                  highlighted
                    ? "border-primary/50 bg-background"
                    : "border-border bg-background/40 opacity-60",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {agent.name}
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {formatDuration(state.duration_seconds)}
                  </span>
                </div>
                <div className="mt-3">
                  <StatusMark state={state} />
                </div>
                {state.description ? (
                  <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
                    {state.description}
                  </p>
                ) : null}
              </div>
              {i < AGENTS.length - 1 ? (
                <ChevronRight className="size-4 shrink-0 text-muted-foreground/50" />
              ) : null}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}