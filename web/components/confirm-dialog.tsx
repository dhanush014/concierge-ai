"use client";

import { useEffect, useId, useRef } from "react";

type Props = {
  open: boolean;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  pending: boolean;
  onConfirm: () => void;
  /** Called on Escape, the cancel button, or after the dialog closes. */
  onClose: () => void;
};

/**
 * Native modal <dialog>: the rest of the page is inert while it is open (focus stays
 * inside) and Escape closes it. The parent returns focus to the opener in onClose.
 */
export function ConfirmDialog({ open, message, confirmLabel, cancelLabel, pending, onConfirm, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => {
        if (pending) e.preventDefault(); // don't close mid-request
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border border-line p-6 text-ink backdrop:bg-black/40"
    >
      <h2 id={titleId} className="mb-6 text-xl font-semibold">
        {message}
      </h2>
      <div className="flex flex-wrap justify-end gap-3">
        <button
          type="button"
          autoFocus
          disabled={pending}
          onClick={onClose}
          className="min-h-11 rounded-md border border-accent px-5 font-medium text-accent hover:bg-accent-soft"
        >
          {cancelLabel}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={onConfirm}
          className="min-h-11 rounded-md bg-danger px-5 font-semibold text-white disabled:opacity-70"
        >
          {pending ? "Cancelling…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
