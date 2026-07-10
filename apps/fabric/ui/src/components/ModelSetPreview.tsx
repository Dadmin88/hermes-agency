import { Loader2 } from "lucide-react";
import type { ModelSetPreview } from "@/api/model-sets";
import { changeDirection, formatModelRef } from "@/lib/model-set-ui";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface ModelSetPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preview: ModelSetPreview | null;
  loading: boolean;
  applying: boolean;
  restartIdleGateways: boolean;
  onRestartIdleGatewaysChange: (value: boolean) => void;
  onApply: () => void;
}

function DirectionGlyph({ direction }: { direction: "up" | "down" | "same" }) {
  if (direction === "up") return <span className="text-emerald-400">↑</span>;
  if (direction === "down") return <span className="text-amber-400">↓</span>;
  return <span className="text-muted-foreground">→</span>;
}

export function ModelSetPreviewDialog({
  open,
  onOpenChange,
  preview,
  loading,
  applying,
  restartIdleGateways,
  onRestartIdleGatewaysChange,
  onApply,
}: ModelSetPreviewDialogProps) {
  const changes = preview?.changes ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[calc(100dvh-2rem)] max-h-[calc(100dvh-2rem)] max-w-3xl flex-col gap-0 overflow-hidden p-0 sm:h-auto sm:max-h-[min(calc(100dvh-2rem),48rem)]">
        <DialogHeader className="shrink-0 border-b border-border/60 px-6 pb-4 pr-12 pt-6">
          <DialogTitle>Apply model set{preview ? `: ${preview.name}` : ""}</DialogTitle>
          <DialogDescription>
            Review agent model changes before applying this preset. Running agents pick up changes on their next heartbeat.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 px-6 py-4">
          {loading ? (
            <div className="flex min-h-0 flex-1 items-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading preview…
            </div>
          ) : (
            <div
              role="region"
              aria-label="Agent model changes"
              tabIndex={0}
              className="min-h-0 flex-1 overflow-auto overscroll-contain rounded-md border border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-muted/95 backdrop-blur">
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Agent</th>
                    <th className="px-3 py-2 font-medium">Current</th>
                    <th className="px-3 py-2 w-8" />
                    <th className="px-3 py-2 font-medium">New</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">
                        No agent model changes for this set.
                      </td>
                    </tr>
                  ) : (
                    changes.map((change) => {
                      const direction = changeDirection(change);
                      return (
                        <tr key={change.agentId} className="border-b border-border/60 last:border-0">
                          <td className="px-3 py-2 font-medium">{change.agentName}</td>
                          <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                            {formatModelRef(change.before.provider, change.before.model)}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <DirectionGlyph direction={direction} />
                          </td>
                          <td
                            className={cn(
                              "px-3 py-2 font-mono text-xs",
                              direction === "same" ? "text-muted-foreground" : "text-foreground",
                            )}
                          >
                            {formatModelRef(change.after.provider, change.after.model)}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}

          <p className="shrink-0 text-xs text-amber-500/90">
            Warning: running agents will pick up changes on next heartbeat. Hermes profile config.yaml files are updated for
            agency profiles (skipping Fabric profile-level overrides).
          </p>

          <div className="flex shrink-0 items-start gap-2 rounded-md border border-border/60 bg-muted/30 p-3">
            <Checkbox
              id="restart-idle-gateways"
              checked={restartIdleGateways}
              onCheckedChange={(checked) => onRestartIdleGatewaysChange(checked === true)}
              disabled={applying}
            />
            <div className="grid gap-1">
              <Label htmlFor="restart-idle-gateways" className="text-sm font-medium leading-none">
                Restart idle gateway agents
              </Label>
              <p className="text-xs text-muted-foreground">
                Reloads Hermes gateways that are not running and have no live heartbeat. Running agents are left untouched.
              </p>
            </div>
          </div>
        </div>

        <DialogFooter className="sticky bottom-0 z-20 shrink-0 border-t border-border/60 bg-background px-6 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={applying}>
            Cancel
          </Button>
          <Button onClick={onApply} disabled={loading || applying || !preview}>
            {applying ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Applying…
              </>
            ) : (
              "Apply now"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}