import { useEffect, useId, useMemo, useState, type CSSProperties, type SVGProps } from "react";
import { Activity, AlertTriangle, Network, ShieldCheck, Zap } from "lucide-react";
import { cn } from "../lib/utils";

type TopologyNodeStatus = "online" | "queued" | "offline" | "blocked";

type TopologyNode = {
  id: string;
  label: string;
  detail: string;
  kind: "relay" | "edge" | "agent";
  status: TopologyNodeStatus;
  x: number;
  y: number;
  z: number;
};

type TopologyEdge = {
  from: string;
  to: string;
  status: "active" | "queued" | "blocked";
  particles: number;
};

type TopologySnapshot = {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
};

type TopologyStats = Record<TopologyNodeStatus, number>;

type CssVars = CSSProperties & Record<`--${string}`, string | number>;

const statusLabels: Record<TopologyNodeStatus, string> = {
  online: "Online",
  queued: "Queued",
  offline: "Offline target",
  blocked: "Needs attention",
};

const statusTone: Record<TopologyNodeStatus, string> = {
  online: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  queued: "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300",
  offline: "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  blocked: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-200",
};

const nodeTone: Record<TopologyNodeStatus, { fill: string; stroke: string; glow: string }> = {
  online: { fill: "#10b981", stroke: "#6ee7b7", glow: "rgba(16, 185, 129, 0.42)" },
  queued: { fill: "#3b82f6", stroke: "#93c5fd", glow: "rgba(59, 130, 246, 0.38)" },
  offline: { fill: "#64748b", stroke: "#cbd5e1", glow: "rgba(100, 116, 139, 0.24)" },
  blocked: { fill: "#f59e0b", stroke: "#fde68a", glow: "rgba(245, 158, 11, 0.38)" },
};

const edgeTone: Record<TopologyEdge["status"], string> = {
  active: "rgba(45, 212, 191, 0.72)",
  queued: "rgba(96, 165, 250, 0.62)",
  blocked: "rgba(245, 158, 11, 0.68)",
};

export const fabricParticleTopologySample: TopologySnapshot = {
  nodes: [
    { id: "vps", label: "VPS relay", detail: "Keryx hub", kind: "relay", status: "online", x: 50, y: 46, z: 1 },
    { id: "katana", label: "Katana", detail: "edge node", kind: "edge", status: "queued", x: 17, y: 24, z: 0.72 },
    { id: "ods", label: "ODS", detail: "edge node", kind: "edge", status: "online", x: 84, y: 27, z: 0.76 },
    { id: "fabric", label: "Fabric", detail: "operator UI", kind: "edge", status: "online", x: 20, y: 76, z: 0.7 },
    { id: "orchestrator", label: "Orchestrator", detail: "routing brain", kind: "agent", status: "queued", x: 80, y: 72, z: 0.66 },
    { id: "review", label: "Review gate", detail: "human governance", kind: "agent", status: "blocked", x: 53, y: 84, z: 0.58 },
  ],
  edges: [
    { from: "vps", to: "katana", status: "queued", particles: 3 },
    { from: "vps", to: "ods", status: "active", particles: 4 },
    { from: "vps", to: "fabric", status: "active", particles: 3 },
    { from: "vps", to: "orchestrator", status: "queued", particles: 4 },
    { from: "orchestrator", to: "review", status: "blocked", particles: 2 },
    { from: "fabric", to: "review", status: "blocked", particles: 2 },
  ],
};

function useReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => setPrefersReducedMotion(media.matches);
    handleChange();
    media.addEventListener?.("change", handleChange);
    return () => media.removeEventListener?.("change", handleChange);
  }, []);

  return prefersReducedMotion;
}

export function summarizeTopology(snapshot: TopologySnapshot): TopologyStats {
  return snapshot.nodes.reduce<TopologyStats>((stats, node) => {
    stats[node.status] += 1;
    return stats;
  }, { online: 0, queued: 0, offline: 0, blocked: 0 });
}

function nodeById(snapshot: TopologySnapshot) {
  return new Map(snapshot.nodes.map((node) => [node.id, node]));
}

function FlowParticle({ index, edge, pathId, reducedMotion }: {
  index: number;
  edge: TopologyEdge;
  pathId: string;
  reducedMotion: boolean;
}) {
  if (reducedMotion) return null;
  const style: CssVars = {
    "--flow-delay": `${index * -0.74}s`,
    "--flow-duration": `${4.6 + edge.particles * 0.42}s`,
  };
  const durationSeconds = 4.6 + edge.particles * 0.42;
  return (
    <circle r={edge.status === "blocked" ? 1.5 : 1.8} className="fabric-flow-particle" style={style}>
      <animateMotion
        dur={`${durationSeconds}s`}
        repeatCount="indefinite"
        begin={`${index * -0.74}s`}
        keyPoints="0;1"
        keyTimes="0;1"
      >
        <mpath href={`#${pathId}`} />
      </animateMotion>
    </circle>
  );
}

function NodeGlyph({ node, ...props }: { node: TopologyNode } & SVGProps<SVGGElement>) {
  const radius = node.kind === "relay" ? 7.6 : node.kind === "edge" ? 5.8 : 5.2;
  const tone = nodeTone[node.status];
  const scale = 0.82 + node.z * 0.25;
  return (
    <g {...props} className={cn("fabric-topology-node", props.className)} style={{ "--node-glow": tone.glow } as CssVars}>
      <circle r={radius * scale + 4} fill={tone.glow} className="fabric-node-halo" />
      <circle r={radius * scale} fill={tone.fill} stroke={tone.stroke} strokeWidth={node.kind === "relay" ? 1.8 : 1.3} />
      {node.kind === "relay" ? (
        <circle r={2.2} fill="rgba(255,255,255,0.88)" />
      ) : node.status === "blocked" ? (
        <path d="M-2.6 2.4 0 -2.8 2.6 2.4Z" fill="rgba(255,255,255,0.9)" />
      ) : (
        <circle r={1.5} fill="rgba(255,255,255,0.82)" />
      )}
    </g>
  );
}

export function FabricParticleTopology({
  snapshot = fabricParticleTopologySample,
  className,
}: {
  snapshot?: TopologySnapshot;
  className?: string;
}) {
  const reducedMotion = useReducedMotion();
  const titleId = useId();
  const descriptionId = useId();
  const nodes = useMemo(() => nodeById(snapshot), [snapshot]);
  const stats = useMemo(() => summarizeTopology(snapshot), [snapshot]);

  return (
    <section className={cn("fabric-particle-visualization overflow-hidden rounded-xl border border-border bg-card shadow-sm", className)}>
      <div className="flex flex-col gap-4 border-b border-border/70 bg-[radial-gradient(circle_at_top_left,rgba(45,212,191,0.14),transparent_32%),radial-gradient(circle_at_bottom_right,rgba(59,130,246,0.14),transparent_36%)] p-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/25 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-cyan-700 dark:text-cyan-200">
            <Network className="h-3.5 w-3.5" />
            Curated prototype
          </div>
          <h2 className="mt-3 text-xl font-semibold tracking-tight">Keryx task-flow topology</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Static React/SVG particle visualization for Hermes Fabric. It uses curated sample data only—no generated code,
            arbitrary JavaScript, GLB, or OBJ execution path.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs sm:min-w-56">
          {(Object.keys(statusLabels) as TopologyNodeStatus[]).map((status) => (
            <div key={status} className={cn("rounded-lg border px-3 py-2", statusTone[status])}>
              <div className="font-semibold tabular-nums">{stats[status]}</div>
              <div>{statusLabels[status]}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="relative min-h-[360px] bg-slate-950 text-white dark:bg-black/20">
          <svg
            viewBox="0 0 100 100"
            role="img"
            aria-labelledby={`${titleId} ${descriptionId}`}
            className="h-full min-h-[360px] w-full"
            preserveAspectRatio="xMidYMid meet"
          >
            <title id={titleId}>Hermes Keryx topology particle map</title>
            <desc id={descriptionId}>
              Sample topology showing a VPS relay, edge nodes, orchestrator, Fabric UI, and review gate with task-flow particles.
            </desc>
            <defs>
              <radialGradient id="fabricTopologyBg" cx="50%" cy="42%" r="68%">
                <stop offset="0%" stopColor="rgba(20,184,166,0.22)" />
                <stop offset="46%" stopColor="rgba(15,23,42,0.78)" />
                <stop offset="100%" stopColor="rgba(2,6,23,1)" />
              </radialGradient>
              <filter id="fabricTopologyGlow" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="2.4" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <rect x="0" y="0" width="100" height="100" fill="url(#fabricTopologyBg)" />
            <g opacity="0.22">
              {Array.from({ length: 7 }).map((_, index) => (
                <ellipse
                  key={index}
                  cx="50"
                  cy="50"
                  rx={18 + index * 6}
                  ry={10 + index * 3.4}
                  fill="none"
                  stroke="rgba(148,163,184,0.38)"
                  strokeWidth="0.25"
                  transform={`rotate(${index * 13} 50 50)`}
                />
              ))}
            </g>
            <g filter="url(#fabricTopologyGlow)">
              {snapshot.edges.map((edge, edgeIndex) => {
                const from = nodes.get(edge.from);
                const to = nodes.get(edge.to);
                if (!from || !to) return null;
                const pathId = `${titleId.replace(/:/g, "")}-edge-${edgeIndex}`;
                const midX = (from.x + to.x) / 2;
                const midY = (from.y + to.y) / 2 - 8 * Math.max(from.z, to.z);
                return (
                  <g key={`${edge.from}-${edge.to}`}>
                    <path
                      id={pathId}
                      d={`M ${from.x} ${from.y} Q ${midX} ${midY} ${to.x} ${to.y}`}
                      fill="none"
                      stroke={edgeTone[edge.status]}
                      strokeWidth={edge.status === "blocked" ? 0.72 : 0.58}
                      strokeDasharray={edge.status === "blocked" ? "1.4 1.7" : undefined}
                    />
                    {Array.from({ length: edge.particles }).map((_, particleIndex) => (
                      <FlowParticle
                        key={particleIndex}
                        index={particleIndex}
                        edge={edge}
                        pathId={pathId}
                        reducedMotion={reducedMotion}
                      />
                    ))}
                  </g>
                );
              })}
              {snapshot.nodes.map((node) => (
                <g key={node.id} transform={`translate(${node.x} ${node.y})`}>
                  <NodeGlyph node={node} />
                  <text
                    y={node.kind === "relay" ? 14 : 11}
                    textAnchor="middle"
                    className="fill-white text-[3px] font-semibold tracking-wide"
                  >
                    {node.label}
                  </text>
                </g>
              ))}
            </g>
          </svg>
          <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-200/80">
            <span className="rounded-full border border-white/10 bg-white/10 px-2 py-1 backdrop-blur">SVG renderer</span>
            <span className="rounded-full border border-white/10 bg-white/10 px-2 py-1 backdrop-blur">No WebGL required</span>
            {reducedMotion ? (
              <span className="rounded-full border border-amber-300/30 bg-amber-300/10 px-2 py-1 text-amber-100 backdrop-blur">
                Reduced-motion fallback active
              </span>
            ) : null}
          </div>
        </div>

        <aside className="space-y-4 border-t border-border/70 p-4 lg:border-l lg:border-t-0">
          <div>
            <h3 className="text-sm font-semibold">Safe prototype contract</h3>
            <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
              <li className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />Static React component with hard-coded sample topology data.</li>
              <li className="flex gap-2"><Zap className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />Task particles are decorative and disabled for reduced-motion users.</li>
              <li className="flex gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />No arbitrary generated JS, model file, or remote asset execution.</li>
            </ul>
          </div>
          <div className="rounded-lg border border-border bg-muted/30 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Activity className="h-4 w-4" />
              Sample status feed
            </div>
            <div className="mt-3 space-y-2">
              {snapshot.nodes.map((node) => (
                <div key={node.id} className="flex items-center justify-between gap-3 text-xs">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{node.label}</div>
                    <div className="truncate text-muted-foreground">{node.detail}</div>
                  </div>
                  <span className={cn("shrink-0 rounded-full border px-2 py-0.5 font-medium", statusTone[node.status])}>
                    {statusLabels[node.status]}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
