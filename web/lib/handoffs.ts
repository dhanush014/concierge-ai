import { ApiError, apiFetch } from "@/lib/api";
import type { ChatMessage } from "@/lib/chat";

export type HandoffReason = "emergency" | "clinical" | "wants_human";
export type HandoffStatus = "open" | "active" | "closed";

export type Handoff = {
  id: string;
  conversation_id: string;
  patient_name: string;
  reason: HandoffReason;
  summary: string;
  status: HandoffStatus;
  staff_id: string | null;
  staff_name: string | null;
  created_at: string;
  closed_at: string | null;
};

export type HandoffDetail = Handoff & { messages: ChatMessage[]; trace_url: string | null };

export const REASON_LABEL: Record<HandoffReason, string> = {
  emergency: "Emergency",
  clinical: "Clinical question",
  wants_human: "Wants a person",
};

export function listHandoffs(): Promise<Handoff[]> {
  return apiFetch<Handoff[]>("/staff/handoffs");
}

export function getHandoff(id: string): Promise<HandoffDetail> {
  return apiFetch<HandoffDetail>(`/staff/handoffs/${encodeURIComponent(id)}`);
}

export function joinHandoff(id: string): Promise<Handoff> {
  return apiFetch<Handoff>(`/staff/handoffs/${encodeURIComponent(id)}/join`, { method: "POST" });
}

export function sendStaffMessage(id: string, content: string): Promise<ChatMessage> {
  return apiFetch<ChatMessage>(`/staff/handoffs/${encodeURIComponent(id)}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function closeHandoff(id: string): Promise<Handoff> {
  return apiFetch<Handoff>(`/staff/handoffs/${encodeURIComponent(id)}/close`, { method: "POST" });
}

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === "handoff_taken") return "Another staff member already joined this chat.";
    if (error.detail === "handoff_closed") return "This chat has already been closed.";
    if (error.detail === "not_joined") return "Join the chat first.";
    if (error.status === 404) return "That handoff no longer exists.";
  }
  return "Something went wrong. Please try again.";
}
