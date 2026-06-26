import { createContext, useContext, useCallback, type ReactNode } from "react";
import { useToast as useToastHook } from "./useToast";

export type ToastType = "success" | "error" | "info" | "warning";

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

// Re-export for convenience
export { useToast } from "./useToast";
