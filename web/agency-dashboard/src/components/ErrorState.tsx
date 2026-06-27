import { cn } from "@/lib/cn";
import Button from "./Button";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}

export default function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-16 text-center",
        className
      )}
    >
      <div className="mb-4 rounded-2xl bg-red-500/10 p-4 text-red-400">
        <AlertTriangle className="h-8 w-8" />
      </div>
      <h3 className="text-lg font-semibold text-slate-200">{title}</h3>
      <p className="mt-1 max-w-md text-sm text-slate-500">{message}</p>
      {onRetry && (
        <Button
          variant="secondary"
          size="sm"
          onClick={onRetry}
          className="mt-4"
        >
          <RefreshCw className="h-4 w-4" />
          Try again
        </Button>
      )}
    </div>
  );
}
