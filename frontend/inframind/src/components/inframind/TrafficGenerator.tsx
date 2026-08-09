import { Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { Panel, PanelLabel } from "./primitives";
import type { TrafficMode } from "@/api/types";

const MODES: { key: TrafficMode; label: string }[] = [
  { key: "malformed", label: "Malformed traffic" },
  { key: "heavy_load", label: "Heavy valid load" },
];

export function TrafficGenerator({
  mode,
  onModeChange,
  onBombard,
  pending,
}: {
  mode: TrafficMode;
  onModeChange: (mode: TrafficMode) => void;
  onBombard: () => void;
  pending: boolean;
}) {
  return (
    <Panel>
      <PanelLabel>Traffic generator</PanelLabel>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          {MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => onModeChange(m.key)}
              className={cn(
                "rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                mode === m.key
                  ? "bg-foreground text-background"
                  : "border border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onBombard}
          disabled={pending}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          <Zap className="size-4" />
          Bombard traffic
        </button>
      </div>
    </Panel>
  );
}