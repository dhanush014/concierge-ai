import type { MessageKind } from "@/lib/chat";

export type ShownMessage = {
  key: string;
  sender: "patient" | "assistant" | "staff";
  kind: MessageKind;
  content: string;
  /** Still streaming in. */
  pending?: boolean;
};

const bubble = "max-w-[85%] whitespace-pre-wrap break-words rounded-lg px-4 py-3";

/**
 * The conversation. Not a live region: streamed words would be read one by one.
 * ChatView announces each finished reply through its own status/alert region.
 */
export function MessageList({ messages }: { messages: ShownMessage[] }) {
  return (
    <ol aria-label="Conversation" className="mb-6 flex flex-col gap-4">
      {messages.map((m) => (
        <li key={m.key} className={m.sender === "patient" ? "flex justify-end" : "flex justify-start"}>
          <Message message={m} />
        </li>
      ))}
    </ol>
  );
}

function Message({ message: m }: { message: ShownMessage }) {
  if (m.sender === "patient") {
    return (
      <div className={`${bubble} bg-accent text-white`}>
        <span className="sr-only">You: </span>
        {m.content}
      </div>
    );
  }

  if (m.kind === "emergency") {
    return (
      <div className={`${bubble} border-l-4 border-danger bg-danger-soft text-danger`}>
        <p className="font-semibold">
          <span className="sr-only">Assistant, urgent: </span>
          {m.content}
        </p>
        <a
          href="tel:911"
          className="mt-3 inline-flex min-h-11 items-center rounded-md bg-danger px-5 font-semibold text-white"
        >
          Call 911
        </a>
      </div>
    );
  }

  if (m.kind === "handoff") {
    return (
      <div className={`${bubble} border-l-4 border-warn bg-warn-soft text-warn`}>
        <p className="mb-1 text-sm font-semibold uppercase tracking-wide">A nurse will follow up</p>
        <p>
          <span className="sr-only">Assistant: </span>
          {m.content}
        </p>
      </div>
    );
  }

  return (
    <div className={`${bubble} bg-accent-soft text-ink`} aria-busy={m.pending || undefined}>
      <span className="sr-only">Assistant: </span>
      {m.content || (m.pending ? <span className="text-muted">Thinking…</span> : null)}
    </div>
  );
}
