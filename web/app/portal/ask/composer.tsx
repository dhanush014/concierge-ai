"use client";

import { useId, type FormEvent, type KeyboardEvent, type RefObject } from "react";
import { MAX_MESSAGE_CHARS } from "@/lib/chat";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  streaming: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
};

/**
 * Question box. Enter sends, Shift+Enter adds a line. While a reply streams only the
 * Send button is disabled: the box stays enabled so keyboard focus never jumps away.
 */
export function Composer({ value, onChange, onSend, streaming, inputRef }: Props) {
  const inputId = useId();
  const noteId = useId();
  const canSend = !streaming && value.trim().length > 0;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (canSend) onSend();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    if (canSend) onSend();
  }

  return (
    <form onSubmit={submit}>
      <label htmlFor={inputId} className="sr-only">
        Your question
      </label>
      <div className="flex items-end gap-3">
        <textarea
          id={inputId}
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxLength={MAX_MESSAGE_CHARS}
          placeholder="Type your question…"
          aria-describedby={noteId}
          className="min-h-11 flex-1 resize-y rounded-md border border-line px-4 py-2 text-lg"
        />
        <button
          type="submit"
          disabled={!canSend}
          className="min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          Send
        </button>
      </div>
      <p id={noteId} className="mt-2 text-muted">
        Not for emergencies.{" "}
        <a href="tel:911" className="font-medium text-accent underline">
          Call 911
        </a>
        .
      </p>
      <p className="mt-1 text-sm text-muted">
        Answers are written by AI and may contain mistakes. For coverage and costs, check with your insurer.
      </p>
    </form>
  );
}
