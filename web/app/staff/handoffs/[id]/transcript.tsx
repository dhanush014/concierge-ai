import type { ChatMessage } from "@/lib/chat";
import { formatTime } from "@/lib/time";

/** The whole conversation as staff see it: who said what, oldest first. */
export function Transcript({ messages, patientName }: { messages: ChatMessage[]; patientName: string }) {
  return (
    <ol aria-label="Transcript" className="mb-6 flex flex-col gap-3">
      {messages.map((m) =>
        m.kind === "notice" ? (
          <li key={m.id} className="text-center text-muted">
            {m.content}
          </li>
        ) : (
          <li
            key={m.id}
            className={`rounded-lg border-l-4 px-4 py-3 ${
              m.kind === "emergency"
                ? "border-danger bg-danger-soft"
                : m.sender === "staff"
                  ? "border-accent bg-white"
                  : m.sender === "patient"
                    ? "border-line bg-accent-soft"
                    : "border-line bg-white"
            }`}
          >
            <p className="mb-1 flex flex-wrap justify-between gap-2 text-sm">
              <span className="font-semibold">
                {m.sender === "patient" ? patientName : m.sender === "staff" ? (m.staff_name ?? "Staff") : "Assistant"}
              </span>
              <span className="text-muted">{formatTime(m.created_at)}</span>
            </p>
            <p className="whitespace-pre-wrap break-words">{m.content}</p>
          </li>
        ),
      )}
    </ol>
  );
}
