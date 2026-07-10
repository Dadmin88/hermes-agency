import { useEffect } from "react";
import { Link } from "@/lib/router";
import { ArrowLeft, FlaskConical } from "lucide-react";
import { FabricParticleTopology } from "../components/FabricParticleTopology";
import { useBreadcrumbs } from "../context/BreadcrumbContext";

export function FabricVisualizationPrototype() {
  const { setBreadcrumbs } = useBreadcrumbs();

  useEffect(() => {
    setBreadcrumbs([{ label: "Fabric visualization prototype" }]);
    return () => setBreadcrumbs([]);
  }, [setBreadcrumbs]);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 sm:p-6">
      <header className="flex flex-col gap-3">
        <Link to="/dashboard" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          Back to dashboard
        </Link>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-border bg-muted/40 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              <FlaskConical className="h-3.5 w-3.5" />
              Experimental route
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">Fabric particle visualization prototype</h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
              A mobile-safe, dark-theme friendly Keryx topology/status map for exploring Hermes Agency task-flow
              particles without executing user-generated visualization code.
            </p>
          </div>
          <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground sm:max-w-xs">
            Hidden from primary navigation. Available in development, or when
            <span className="font-mono text-foreground"> VITE_ENABLE_FABRIC_VIS_PROTOTYPE=true</span>.
          </div>
        </div>
      </header>

      <FabricParticleTopology />
    </div>
  );
}
