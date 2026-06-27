import { useState, useCallback, useRef } from "react";

export type ToastType = "success" | "error" | "info" | "warning";

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

let globalToasts: Toast[] = [];
let globalListeners: Set<() => void> = new Set();

function notify() {
  globalListeners.forEach((l) => l());
}

export function addToast(type: ToastType, message: string) {
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const toast: Toast = { id, type, message };
  globalToasts = [...globalToasts, toast];
  notify();
  setTimeout(() => {
    globalToasts = globalToasts.filter((t) => t.id !== id);
    notify();
  }, 4000);
}

export function removeToast(id: string) {
  globalToasts = globalToasts.filter((t) => t.id !== id);
  notify();
}

export function useToast() {
  const [, setTick] = useState(0);

  const subscribe = useCallback(() => {
    const listener = () => setTick((t) => t + 1);
    globalListeners.add(listener);
    return () => {
      globalListeners.delete(listener);
    };
  }, []);

  // Subscribe on first render
  useState(() => {
    const listener = () => setTick((t) => t + 1);
    globalListeners.add(listener);
  });

  return {
    toasts: globalToasts,
    addToast,
    removeToast,
  };
}
