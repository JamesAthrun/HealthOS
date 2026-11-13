"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

type Tone = "success" | "warning" | "error";
export type ToastAction = { label: string; onClick: () => void };
type Toast = { id: number; message: string; tone: Tone; action?: ToastAction };

const ToastContext = createContext<(message: string, tone?: Tone, action?: ToastAction) => void>(() => undefined);

/** 屏幕底部的轻提示：保存、删除后统一用它反馈；可带一个操作按钮（如“撤销”） */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);

  const show = useCallback((message: string, tone: Tone = "success", action?: ToastAction) => {
    setToast({ id: Date.now(), message, tone, action });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), toast.action ? 6000 : toast.tone === "success" ? 2200 : 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && (
        <div key={toast.id} className={`toast toast-${toast.tone}`} role="status" onClick={() => setToast(null)}>
          {toast.message}
          {toast.action && (
            <button
              type="button"
              className="toast-action"
              onClick={(e) => { e.stopPropagation(); setToast(null); toast.action?.onClick(); }}
            >
              {toast.action.label}
            </button>
          )}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
