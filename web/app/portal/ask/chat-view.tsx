"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { StatusMessage, type Status } from "@/components/status-message";
import { isRetryable, isStatus } from "@/lib/api";
import {
  getConversation,
  getLatestConversation,
  leaveHandoff,
  MAX_MESSAGE_CHARS,
  messageFor,
  streamChat,
  type Conversation,
} from "@/lib/chat";
import { Composer } from "./composer";
import { MessageList, withCitations, type ShownMessage } from "./message-list";
import { arrivals, empty, fromConversation, staffInChat, type Session } from "./session";
import { useLiveConversation } from "./use-live-conversation";

const BASE = "/portal/ask";
const SUGGESTIONS = ["When is my next appointment?", "What documents have I uploaded?", "What were my past visits?"];

/**
 * The Ask tab. URL: no ?c = reopen your latest conversation; ?c=<id> = that one;
 * ?c=new = a fresh one (created by the first message, then the URL becomes its id).
 * &ask=<text> puts a suggested question in the box; the patient still presses Send.
 * During a handoff the assistant is quiet; staff replies arrive live.
 */
export function ChatView() {
  const router = useRouter();
  const params = useSearchParams();
  const urlKey = params.get("c") ?? "latest";
  const ask = params.get("ask");

  const [session, setSession] = useState<Session>(() => empty(urlKey === "new" ? "new" : ""));
  const [loadError, setLoadError] = useState<{ key: string; error: unknown } | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [status, setStatus] = useState<Status>(null);
  const [input, setInput] = useState("");
  // Prefill once per ?ask= visit (the page may stay mounted between visits).
  const [asked, setAsked] = useState<string | null>(null);
  if (ask !== asked) {
    setAsked(ask);
    if (ask) setInput(ask.slice(0, MAX_MESSAGE_CHARS));
  }
  const [streaming, setStreaming] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [announced, setAnnounced] = useState({ polite: "", urgent: "" });
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef(session);
  useEffect(() => {
    sessionRef.current = session;
  });

  // Where we're navigating ourselves (New conversation, or a new chat getting its id).
  // Until the URL gets there, the old URL must not trigger a load.
  const [navTo, setNavTo] = useState<string | null>(null);
  if (navTo !== null && urlKey === navTo) setNavTo(null);
  // Browser Back/Forward onto ?c=new: show an empty chat.
  if (navTo === null && urlKey === "new" && session.key !== "new") setSession(empty("new"));

  const needsLoad = navTo === null && urlKey !== "new" && urlKey !== session.key && loadError?.key !== urlKey;

  // Load the conversation the URL points at (unless it is already on screen).
  useEffect(() => {
    if (!needsLoad) return;
    let active = true;
    const load = urlKey === "latest" ? getLatestConversation() : getConversation(urlKey);
    load.then(
      (convo) => {
        if (!active) return;
        if (convo === null) return setSession(empty("latest"));
        setSession(fromConversation(convo));
        if (urlKey === "latest") {
          setNavTo(convo.id);
          router.replace(`${BASE}?c=${convo.id}`);
        }
      },
      (error: unknown) => {
        if (!active) return;
        if (isStatus(error, 401)) return router.replace("/login");
        if (isStatus(error, 404)) {
          // Not yours or gone: say so and offer a fresh chat.
          setStatus({ kind: "error", text: messageFor(error) });
          return setSession(empty(urlKey));
        }
        setLoadError({ key: urlKey, error });
      },
    );
    return () => {
      active = false;
    };
  }, [needsLoad, urlKey, reloadTick, router]);

  // Staff replies, "joined" notices and status changes, live.
  useLiveConversation(session.conversationId, streaming, (c: Conversation) => {
    const before = sessionRef.current;
    if (before.conversationId !== c.id) return;
    const next = fromConversation(c);
    setSession({ ...next, key: before.key });
    const said = arrivals(before.messages, next.messages);
    if (said) setAnnounced({ polite: said, urgent: "" });
  });

  useEffect(() => {
    if (ask) inputRef.current?.focus();
  }, [ask]);

  // Keep the newest message (and the input) in view as the reply streams in.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [session.messages]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || streaming) return;
    setStatus(null);
    setAnnounced({ polite: "", urgent: "" });
    setInput("");
    setStreaming(true);
    const waiting = session.status === "handoff"; // a nurse answers now, not the assistant
    const stamp = Date.now();
    const replyKey = `reply-${stamp}`;
    const blank: ShownMessage = { key: replyKey, sender: "assistant", kind: "text", content: "", pending: true };
    setSession((s) => ({
      ...s,
      messages: [
        ...s.messages,
        { key: `you-${stamp}`, sender: "patient", kind: "text", content: question },
        ...(waiting ? [] : [blank]), // "Thinking…" only when the assistant will answer
      ],
    }));
    inputRef.current?.focus(); // e.g. after a suggestion button, which then disappears

    // The reply bubble, found by key (notices may come after it); created on first use.
    const patchReply = (patch: (m: ShownMessage) => Partial<ShownMessage>) =>
      setSession((s) => {
        const i = s.messages.findIndex((m) => m.key === replyKey);
        const messages = [...s.messages];
        if (i < 0) messages.push({ ...blank, ...patch(blank) });
        else messages[i] = { ...messages[i], ...patch(messages[i]) };
        return { ...s, messages };
      });
    const dropReply = () => setSession((s) => ({ ...s, messages: s.messages.filter((m) => m.key !== replyKey) }));

    let conversationId = session.conversationId;
    const adopt = (id: string) => {
      setSession((s) => ({ ...s, key: id, conversationId: id }));
      if (urlKey !== id) navigate(id, "replace");
    };
    let reply = "";
    const notices: string[] = [];
    try {
      const done = await streamChat(conversationId, question, {
        onConversation: (id) => {
          conversationId = id;
        },
        onToken: (t) => {
          reply += t;
          patchReply((m) => ({ content: m.content + t }));
        },
        onNotice: (t) => {
          notices.push(t);
          setSession((s) => ({
            ...s,
            messages: [...s.messages, { key: `notice-${stamp}-${notices.length}`, sender: "assistant", kind: "notice", content: t }],
          }));
        },
      });
      if (reply) patchReply(() => ({ kind: done.kind ?? "text", pending: false, sources: done.sources }));
      else dropReply();
      setSession((s) => ({ ...s, status: done.status }));
      const spoken = [withCitations(reply, done.sources), ...notices].filter(Boolean).join(" ") || "Sent. The nurse will see your message.";
      setAnnounced(done.kind === "emergency" ? { polite: "", urgent: spoken } : { polite: reply ? `Assistant: ${spoken}` : spoken, urgent: "" });
      if (conversationId) adopt(conversationId);
    } catch (error) {
      dropReply(); // the unfinished reply
      if (isStatus(error, 401)) return router.replace("/login");
      if (isStatus(error, 404)) {
        setStatus({ kind: "error", text: messageFor(error) });
        setSession(empty("new"));
        navigate("new", "replace");
        return;
      }
      if (conversationId) adopt(conversationId); // the question was saved; retry continues it
      setStatus({
        kind: "error",
        text: messageFor(error),
        onRetry: isRetryable(error) ? () => send(question) : undefined,
      });
    } finally {
      setStreaming(false);
    }
  }

  // End the nurse chat (a nurse may never have come, or has gone): the assistant is back.
  async function leaveNurseChat() {
    const id = session.conversationId;
    if (!id || leaving) return;
    setStatus(null);
    setLeaving(true);
    try {
      const convo = await leaveHandoff(id).catch((error: unknown) => {
        if (isStatus(error, 409)) return getConversation(id); // already ended by the nurse
        throw error;
      });
      setSession((s) => ({ ...fromConversation(convo), key: s.key }));
      setAnnounced({ polite: "You left the nurse chat. The assistant is back.", urgent: "" });
      inputRef.current?.focus();
    } catch (error) {
      if (isStatus(error, 401)) return router.replace("/login");
      setStatus({ kind: "error", text: messageFor(error), onRetry: isRetryable(error) ? leaveNurseChat : undefined });
    } finally {
      setLeaving(false);
    }
  }

  function navigate(key: string, how: "push" | "replace") {
    setNavTo(key);
    router[how](`${BASE}?c=${key}`);
  }

  function newConversation() {
    setStatus(null);
    setLoadError(null);
    setSession(empty("new"));
    navigate("new", "push");
    inputRef.current?.focus();
  }

  const failed = loadError?.key === urlKey ? loadError.error : null;
  const shown: Status =
    status ??
    (failed
      ? {
          kind: "error",
          text: messageFor(failed),
          onRetry: isRetryable(failed)
            ? () => {
                setLoadError(null);
                setReloadTick((t) => t + 1);
              }
            : undefined,
        }
      : null);
  const loading = needsLoad && !failed;
  const nurse = staffInChat(session);

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-semibold">Ask</h1>
        <button
          type="button"
          onClick={newConversation}
          disabled={streaming}
          className="min-h-11 rounded-md border border-accent px-5 font-semibold text-accent hover:bg-accent-soft disabled:opacity-50"
        >
          New conversation
        </button>
      </div>

      <StatusMessage status={shown} />

      {/* Screen readers hear each finished reply once, not every streamed word. */}
      <div role="status" aria-live="polite" className="sr-only">
        {announced.polite}
      </div>
      <div role="alert" className="sr-only">
        {announced.urgent}
      </div>

      {loading ? (
        <p className="mb-6 text-muted">Loading…</p>
      ) : session.messages.length === 0 ? (
        <section aria-labelledby="suggest-heading" className="mb-6">
          <h2 id="suggest-heading" className="mb-3 text-lg font-semibold">
            Try asking
          </h2>
          <ul className="flex flex-wrap gap-3">
            {SUGGESTIONS.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  onClick={() => send(s)}
                  disabled={streaming}
                  className="min-h-11 rounded-full border border-line px-4 text-left hover:border-accent hover:bg-accent-soft"
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <MessageList messages={session.messages} />
      )}

      {session.status === "handoff" && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border-l-4 border-warn bg-warn-soft px-4 py-3">
          <p className="font-medium text-warn">
            {nurse ? `You're chatting with ${nurse}.` : "Connecting you to a nurse… They'll see your messages here."}
          </p>
          <button
            type="button"
            onClick={leaveNurseChat}
            disabled={streaming || leaving}
            className="min-h-11 rounded-md border border-warn px-4 font-semibold text-warn hover:bg-white disabled:opacity-50"
          >
            Back to the assistant
          </button>
        </div>
      )}

      <Composer value={input} onChange={setInput} onSend={() => send(input)} streaming={streaming} inputRef={inputRef} />
      <div ref={endRef} />
    </>
  );
}
