"use client";

import { useId, useState, type FormEvent, type KeyboardEvent } from "react";
import { MAX_MESSAGE_CHARS } from "@/lib/chat";

/** Staff reply box. Enter sends, Shift+Enter adds a line. Clears only after a send succeeds. */
export function ReplyBox({ onSend }: { onSend: (text: string) => Promise<boolean> }) {
  const id = useId();
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const canSend = !pending && value.trim().length > 0;

  async function send() {
    if (!canSend) return;
    setPending(true);
    if (await onSend(value.trim())) setValue("");
    setPending(false);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    void send();
  }

  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void send();
      }}
      className="mb-6"
    >
      <label htmlFor={id} className="mb-2 block font-semibold">
        Reply to the patient
      </label>
      <div className="flex items-end gap-3">
        <textarea
          id={id}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxLength={MAX_MESSAGE_CHARS}
          className="min-h-11 flex-1 resize-y rounded-md border border-line px-4 py-2 text-lg"
        />
        <button
          type="submit"
          disabled={!canSend}
          className="min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? "Sending…" : "Send"}
        </button>
      </div>
    </form>
  );
}
