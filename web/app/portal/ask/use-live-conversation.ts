"use client";

import { useEffect, useRef } from "react";
import { getConversation, type Conversation } from "@/lib/chat";
import { watchTables } from "@/lib/realtime";

/**
 * Keep an open conversation fresh: staff replies, "joined" notices and status changes
 * arrive through Supabase Realtime, then the conversation is reloaded from the API.
 * While `busy` (our own reply is streaming) reloads wait, so they can't overwrite the
 * half-streamed message; one reload runs as soon as it finishes.
 */
export function useLiveConversation(
  conversationId: string | null,
  busy: boolean,
  onFresh: (conversation: Conversation) => void,
): void {
  const busyRef = useRef(busy);
  const missed = useRef(false);
  const onFreshRef = useRef(onFresh);
  const reloadRef = useRef<() => void>(() => {});

  useEffect(() => {
    onFreshRef.current = onFresh;
  });

  useEffect(() => {
    if (!conversationId) return;
    let active = true;
    const reload = () => {
      if (busyRef.current) {
        missed.current = true;
        return;
      }
      getConversation(conversationId).then(
        (c) => active && onFreshRef.current(c),
        () => {}, // a failed refresh is retried by the next change; the page keeps what it has
      );
    };
    reloadRef.current = reload;
    const stop = watchTables(
      "conversation",
      [
        { table: "messages", filter: `conversation_id=eq.${conversationId}` },
        { table: "conversations", filter: `id=eq.${conversationId}` },
      ],
      reload,
    );
    return () => {
      active = false;
      stop();
    };
  }, [conversationId]);

  useEffect(() => {
    busyRef.current = busy;
    if (!busy && missed.current) {
      missed.current = false;
      reloadRef.current();
    }
  }, [busy]);
}
