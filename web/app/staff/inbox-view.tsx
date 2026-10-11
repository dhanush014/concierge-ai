"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { StatusMessage } from "@/components/status-message";
import { isRetryable } from "@/lib/api";
import { REASON_LABEL, listHandoffs, messageFor, type Handoff, type HandoffStatus } from "@/lib/handoffs";
import { watchTables } from "@/lib/realtime";
import { formatDateTime } from "@/lib/time";
import { useApi } from "@/lib/use-api";

const SECTIONS: { status: HandoffStatus; title: string; empty: string }[] = [
  { status: "open", title: "Open", empty: "No one is waiting." },
  { status: "active", title: "Active", empty: "No chats in progress." },
  { status: "closed", title: "Closed", empty: "Nothing closed yet." },
];

/** Live list of handoff tickets. New ones appear without a refresh (Supabase Realtime). */
export function InboxView() {
  const tickets = useApi("handoffs", listHandoffs);
  const reload = tickets.reload;
  const [announced, setAnnounced] = useState("");
  const knownOpen = useRef<Set<string> | null>(null);

  useEffect(() => watchTables("inbox", [{ table: "handoffs" }], reload), [reload]);

  // Tell screen readers about tickets that arrived since the last load.
  useEffect(() => {
    if (!tickets.data) return;
    const open = tickets.data.filter((t) => t.status === "open");
    if (knownOpen.current !== null) {
      const fresh = open.filter((t) => !knownOpen.current!.has(t.id));
      if (fresh.length > 0) {
        setAnnounced(fresh.map((t) => `New handoff: ${t.patient_name}, ${REASON_LABEL[t.reason]}.`).join(" "));
      }
    }
    knownOpen.current = new Set(open.map((t) => t.id));
  }, [tickets.data]);

  return (
    <>
      <h1 className="mb-6 text-3xl font-semibold">Staff inbox</h1>
      <StatusMessage
        status={
          tickets.error
            ? { kind: "error", text: messageFor(tickets.error), onRetry: isRetryable(tickets.error) ? reload : undefined }
            : null
        }
      />
      <div role="status" aria-live="polite" className="sr-only">
        {announced}
      </div>

      {!tickets.data ? (
        <p className="text-muted">{tickets.loading ? "Loading…" : ""}</p>
      ) : (
        SECTIONS.map(({ status, title, empty }) => {
          const list = tickets.data!.filter((t) => t.status === status);
          return (
            <section key={status} aria-labelledby={`${status}-heading`} className="mb-10">
              <h2 id={`${status}-heading`} className="mb-4 flex items-center gap-3 text-2xl font-semibold">
                {title}
                {status === "open" && list.length > 0 && (
                  <span className="rounded-full bg-danger px-3 py-0.5 text-base font-semibold text-white">
                    {list.length}
                    <span className="sr-only"> waiting</span>
                  </span>
                )}
              </h2>
              {list.length === 0 ? (
                <p className="text-muted">{empty}</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {list.map((t) => (
                    <li key={t.id}>
                      <TicketCard ticket={t} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })
      )}
    </>
  );
}

function TicketCard({ ticket: t }: { ticket: Handoff }) {
  const urgent = t.reason === "emergency" && t.status !== "closed";
  return (
    <Link
      href={`/staff/handoffs/${t.id}`}
      className={`block rounded-lg border p-5 hover:bg-accent-soft ${urgent ? "border-l-4 border-danger" : "border-line hover:border-accent"}`}
    >
      <span className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-lg font-semibold">{t.patient_name}</span>
        <span className="text-muted">{formatDateTime(t.created_at)}</span>
      </span>
      <span className={`block font-medium ${urgent ? "text-danger" : "text-accent"}`}>{REASON_LABEL[t.reason]}</span>
      <span className="mt-1 block text-ink">{t.summary}</span>
      {t.staff_name && t.status === "active" && <span className="mt-1 block text-muted">With {t.staff_name}</span>}
    </Link>
  );
}
