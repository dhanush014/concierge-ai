"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { StatusMessage, type Status } from "@/components/status-message";
import { isRetryable, isStatus } from "@/lib/api";
import { REASON_LABEL, closeHandoff, getHandoff, joinHandoff, messageFor, sendStaffMessage } from "@/lib/handoffs";
import { watchTables } from "@/lib/realtime";
import { createClient } from "@/lib/supabase/browser";
import { formatDateTime } from "@/lib/time";
import { useApi } from "@/lib/use-api";
import { ReplyBox } from "./reply-box";
import { Transcript } from "./transcript";

const STATUS_LABEL = { open: "Waiting", active: "In progress", closed: "Closed" } as const;

/** One handoff: summary, live transcript, Join, reply, Close. */
export function HandoffView({ id }: { id: string }) {
  const router = useRouter();
  const ticket = useApi(`handoff-${id}`, () => getHandoff(id));
  const { reload } = ticket;
  const data = ticket.data;
  const [myId, setMyId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [announced, setAnnounced] = useState("");
  const seen = useRef<Set<string> | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    void createClient()
      .auth.getSession()
      .then(({ data: s }) => setMyId(s.session?.user.id ?? null));
  }, []);

  // Live: new patient messages and status changes (e.g. another nurse joined).
  const conversationId = data?.conversation_id;
  useEffect(() => {
    if (!conversationId) return;
    return watchTables(
      "handoff",
      [
        { table: "messages", filter: `conversation_id=eq.${conversationId}` },
        { table: "handoffs", filter: `id=eq.${id}` },
      ],
      reload,
    );
  }, [conversationId, id, reload]);

  // Screen readers hear what the patient writes while staff are here.
  useEffect(() => {
    if (!data) return;
    if (seen.current !== null) {
      const fresh = data.messages.filter((m) => !seen.current!.has(m.id) && m.sender === "patient");
      if (fresh.length > 0) setAnnounced(fresh.map((m) => `${data.patient_name}: ${m.content}`).join(" "));
    }
    seen.current = new Set(data.messages.map((m) => m.id));
  }, [data]);

  async function act(action: () => Promise<unknown>): Promise<boolean> {
    setPending(true);
    setStatus(null);
    try {
      await action();
      return true;
    } catch (error) {
      if (isStatus(error, 401)) router.replace("/login");
      else setStatus({ kind: "error", text: messageFor(error) });
      return false;
    } finally {
      setPending(false);
      reload();
    }
  }

  if (!data) {
    const error = ticket.error;
    return error ? (
      <StatusMessage status={{ kind: "error", text: messageFor(error), onRetry: isRetryable(error) ? reload : undefined }} focus />
    ) : (
      <p className="text-muted">Loading…</p>
    );
  }

  const mine = data.status === "active" && myId !== null && data.staff_id === myId;
  const urgent = data.reason === "emergency" && data.status !== "closed";

  return (
    <>
      <Link href="/staff" className="mb-6 inline-block font-medium text-accent underline">
        Back to inbox
      </Link>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-3xl font-semibold">{data.patient_name}</h1>
        <span className="rounded-full border border-line px-3 py-1 font-medium">{STATUS_LABEL[data.status]}</span>
      </div>

      <dl className={`mb-6 rounded-lg border-l-4 px-5 py-4 ${urgent ? "border-danger bg-danger-soft" : "border-accent bg-accent-soft"}`}>
        <dt className="text-sm font-semibold uppercase tracking-wide text-muted">Reason</dt>
        <dd className={`mb-3 text-lg font-semibold ${urgent ? "text-danger" : ""}`}>{REASON_LABEL[data.reason]}</dd>
        <dt className="text-sm font-semibold uppercase tracking-wide text-muted">AI summary</dt>
        <dd className="mb-3">{data.summary}</dd>
        <dt className="text-sm font-semibold uppercase tracking-wide text-muted">Opened</dt>
        <dd>{formatDateTime(data.created_at)}</dd>
      </dl>
      {data.trace_url && (
        <a href={data.trace_url} target="_blank" rel="noopener noreferrer" className="mb-6 inline-block font-medium text-accent underline">
          View trace<span className="sr-only"> in LangSmith (opens in a new tab)</span>
        </a>
      )}

      <StatusMessage status={status} focus />
      <div role="status" aria-live="polite" className="sr-only">
        {announced}
      </div>

      <h2 className="mb-3 text-2xl font-semibold">Conversation</h2>
      <Transcript messages={data.messages} patientName={data.patient_name} />

      {data.status === "open" && (
        <button
          type="button"
          disabled={pending}
          onClick={() => act(() => joinHandoff(id))}
          className="min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
        >
          {pending ? "Joining…" : "Join"}
        </button>
      )}
      {data.status === "active" && !mine && <p className="text-muted">{data.staff_name ?? "Another staff member"} is handling this chat.</p>}
      {mine && (
        <>
          <ReplyBox onSend={(text) => act(() => sendStaffMessage(id, text))} />
          <button
            ref={closeButton}
            type="button"
            onClick={() => setConfirming(true)}
            className="min-h-11 rounded-md border border-accent px-5 font-semibold text-accent hover:bg-accent-soft"
          >
            Close
          </button>
        </>
      )}
      {data.status === "closed" && data.closed_at && <p className="text-muted">Closed {formatDateTime(data.closed_at)}.</p>}

      <ConfirmDialog
        open={confirming}
        message="Close this chat? The patient goes back to the assistant."
        cancelLabel="Keep chatting"
        confirmLabel="Close chat"
        pendingLabel="Closing…"
        pending={pending}
        onConfirm={async () => {
          await act(() => closeHandoff(id));
          setConfirming(false);
        }}
        onClose={() => {
          setConfirming(false);
          closeButton.current?.focus();
        }}
      />
    </>
  );
}
