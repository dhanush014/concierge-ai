"use client";

import { useEffect, useRef } from "react";

export type Status = {
  kind: "success" | "error";
  text: string;
  /** Shown as a Retry button (500s and network failures). */
  onRetry?: () => void;
} | null;

/**
 * One live region per screen. Screen readers announce changes; when `focus` is set
 * the region also takes keyboard focus so the user lands on the result of an action.
 */
export function StatusMessage({ status, focus = false }: { status: Status; focus?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  // Keyed on the text, not the object, so re-renders don't steal focus.
  const text = status?.text;
  useEffect(() => {
    if (!focus || !text) return;
    // Next tick: a closing <dialog> restores focus on its own; this must win.
    const id = setTimeout(() => ref.current?.focus(), 0);
    return () => clearTimeout(id);
  }, [focus, text]);

  const tone =
    status?.kind === "error"
      ? "border-danger bg-red-50 text-danger"
      : "border-accent bg-accent-soft text-accent-hover";

  return (
    <div ref={ref} tabIndex={-1} role="status" aria-live="polite" className="outline-none">
      {status && (
        <div className={`mb-6 flex flex-wrap items-center gap-4 rounded-md border-l-4 px-4 py-3 ${tone}`}>
          <p className="font-medium">{status.text}</p>
          {status.onRetry && (
            <button
              type="button"
              onClick={status.onRetry}
              className="min-h-11 rounded-md border border-current px-4 font-medium"
            >
              Retry
            </button>
          )}
        </div>
      )}
    </div>
  );
}
