"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { StatusMessage, type Status } from "@/components/status-message";
import { isRetryable, isStatus } from "@/lib/api";
import {
  getConversation,
  getLatestConversation,
  messageFor,
  streamChat,
  type Conversation,
} from "@/lib/chat";
import { Composer } from "./composer";
import { MessageList, type ShownMessage } from "./message-list";

const BASE = "/portal/ask";
const SUGGESTIONS = ["When is my next appointment?", "What documents have I uploaded?", "What were my past visits?"];

/** What is on screen. `key` is the URL state it belongs to: a conversation id, "new" or "latest". */
type Session = { key: string; conversationId: string | null; messages: ShownMessage[] };

function fromConversation(c: Conversation): Session {
  return {
    key: c.id,
    conversationId: c.id,
    messages: c.messages.map((m) => ({ key: m.id, sender: m.sender, kind: m.kind, content: m.content })),
  };
}

const empty = (key: string): Session => ({ key, conversationId: null, messages: [] });

/**
 * The Ask tab. URL: no ?c = reopen your latest conversation; ?c=<id> = that one;
 * ?c=new = a fresh one (created by the first message, then the URL becomes its id).
 */
export function ChatView() {
  const router = useRouter();
  const urlKey = useSearchParams().get("c") ?? "latest";

  const [session, setSession] = useState<Session>(() => empty(urlKey === "new" ? "new" : ""));
  const [loadError, setLoadError] = useState<{ key: string; error: unknown } | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [status, setStatus] = useState<Status>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [announced, setAnnounced] = useState({ polite: "", urgent: "" });
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

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

  // Keep the newest message (and the input) in view as the reply streams in.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [session.messages]);

  function updateLast(patch: Partial<ShownMessage> | ((m: ShownMessage) => Partial<ShownMessage>)) {
    setSession((s) => {
      const messages = [...s.messages];
      const last = messages[messages.length - 1];
      messages[messages.length - 1] = { ...last, ...(typeof patch === "function" ? patch(last) : patch) };
      return { ...s, messages };
    });
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || streaming) return;
    setStatus(null);
    setAnnounced({ polite: "", urgent: "" });
    setInput("");
    setStreaming(true);
    const stamp = Date.now();
    setSession((s) => ({
      ...s,
      messages: [
        ...s.messages,
        { key: `you-${stamp}`, sender: "patient", kind: "text", content: question },
        { key: `reply-${stamp}`, sender: "assistant", kind: "text", content: "", pending: true },
      ],
    }));
    inputRef.current?.focus(); // e.g. after a suggestion button, which then disappears

    let conversationId = session.conversationId;
    const adopt = (id: string) => {
      setSession((s) => ({ ...s, key: id, conversationId: id }));
      if (urlKey !== id) navigate(id, "replace");
    };
    let reply = "";
    try {
      const done = await streamChat(conversationId, question, {
        onConversation: (id) => {
          conversationId = id;
        },
        onToken: (t) => {
          reply += t;
          updateLast((m) => ({ content: m.content + t }));
        },
      });
      updateLast({ kind: done.kind, pending: false });
      setAnnounced(done.kind === "emergency" ? { polite: "", urgent: reply } : { polite: `Assistant: ${reply}`, urgent: "" });
      if (conversationId) adopt(conversationId);
    } catch (error) {
      setSession((s) => ({ ...s, messages: s.messages.slice(0, -1) })); // drop the unfinished reply
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

      <Composer value={input} onChange={setInput} onSend={() => send(input)} streaming={streaming} inputRef={inputRef} />
      <div ref={endRef} />
    </>
  );
}
