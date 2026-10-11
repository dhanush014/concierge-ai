import type { Conversation, ConversationStatus } from "@/lib/chat";
import type { ShownMessage } from "./message-list";

/** What is on screen. `key` is the URL state it belongs to: a conversation id, "new" or "latest". */
export type Session = {
  key: string;
  conversationId: string | null;
  status: ConversationStatus;
  messages: ShownMessage[];
};

export function fromConversation(c: Conversation): Session {
  return {
    key: c.id,
    conversationId: c.id,
    status: c.status,
    messages: c.messages.map((m) => ({
      key: m.id,
      sender: m.sender,
      kind: m.kind,
      content: m.content,
      staffName: m.staff_name,
      sources: m.sources,
    })),
  };
}

export const empty = (key: string): Session => ({ key, conversationId: null, status: "bot", messages: [] });

/**
 * Text for screen readers when a live update brings messages the patient didn't
 * trigger: staff replies and notices like "Nurse Kim joined the chat". Messages already
 * on screen (same id, or a notice with the same text shown from the stream) are skipped.
 */
export function arrivals(before: ShownMessage[], after: ShownMessage[]): string {
  const seenKeys = new Set(before.map((m) => m.key));
  const seenNotices = new Set(before.filter((m) => m.kind === "notice").map((m) => m.content));
  return after
    .filter((m) => !seenKeys.has(m.key))
    .filter((m) => m.sender === "staff" || (m.kind === "notice" && !seenNotices.has(m.content)))
    .map((m) => (m.sender === "staff" && m.kind === "text" ? `${m.staffName ?? "Staff"}: ${m.content}` : m.content))
    .join(" ");
}

/** The staff member chatting in the current handoff, if one has joined. */
export function staffInChat(s: Session): string | null {
  if (s.status !== "handoff") return null;
  // Walk back to where this handoff started; an earlier handoff's nurse doesn't count.
  for (const m of [...s.messages].reverse()) {
    if (m.sender === "staff") return m.staffName ?? "A staff member";
    if (m.sender === "assistant" && (m.kind === "handoff" || m.kind === "emergency")) return null;
  }
  return null;
}
