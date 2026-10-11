import { ApiError, apiFetch, apiResponse } from "@/lib/api";

export type MessageKind = "text" | "emergency" | "handoff";

export type ChatMessage = {
  id: string;
  sender: "patient" | "assistant" | "staff";
  kind: MessageKind;
  content: string;
  created_at: string;
};

export type Conversation = {
  id: string;
  status: "bot" | "handoff" | "closed";
  created_at: string;
  messages: ChatMessage[];
};

/** The last event of a successful reply. */
export type ChatDone = { kind: MessageKind };

type StreamEvent =
  | { type: "conversation"; id: string }
  | { type: "token"; text: string }
  | ({ type: "done" } & ChatDone)
  | { type: "error"; message: string };

/** The reply failed after the question was saved (the server sent an "error" event). */
export class ChatStreamError extends Error {
  constructor() {
    super("chat stream failed");
    this.name = "ChatStreamError";
  }
}

export const MAX_MESSAGE_CHARS = 2000; // same limit as the API

export function getConversation(id: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/me/conversations/${encodeURIComponent(id)}`);
}

/** Your newest conversation, or null if you have none. */
export function getLatestConversation(): Promise<Conversation | null> {
  return apiFetch<Conversation | null>("/me/conversations/latest");
}

type Handlers = {
  onConversation: (id: string) => void;
  onToken: (text: string) => void;
};

/**
 * Send a message and read the Server-Sent Events reply as it streams. Not EventSource:
 * that can't send the Authorization header. Resolves on "done"; throws ApiError
 * (HTTP/network) or ChatStreamError (the reply failed part-way).
 */
export async function streamChat(conversationId: string | null, message: string, handlers: Handlers): Promise<ChatDone> {
  const resp = await apiResponse("/me/chat", {
    method: "POST",
    body: JSON.stringify(conversationId ? { conversation_id: conversationId, message } : { message }),
  });
  if (!resp.body) throw new ChatStreamError();

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        const event = JSON.parse(part.slice(6)) as StreamEvent;
        if (event.type === "conversation") handlers.onConversation(event.id);
        else if (event.type === "token") handlers.onToken(event.text);
        else if (event.type === "done") return { kind: event.kind };
        else throw new ChatStreamError();
      }
    }
  } catch (error) {
    if (error instanceof ChatStreamError) throw error;
    throw new ApiError(0, "network"); // connection dropped mid-reply
  } finally {
    reader.releaseLock();
  }
  throw new ChatStreamError(); // stream ended without "done"
}

export function messageFor(error: unknown): string {
  if (error instanceof ChatStreamError) return "Sorry, I couldn't answer that. Please try again.";
  if (error instanceof ApiError && error.status === 404) return "That conversation isn't available.";
  return "Something went wrong. Please try again.";
}
