import type { Metadata } from "next";
import { Suspense } from "react";
import { ChatView } from "./chat-view";

export const metadata: Metadata = { title: "Ask" };

export default function AskPage() {
  return (
    <Suspense fallback={<p className="text-muted">Loading…</p>}>
      <ChatView />
    </Suspense>
  );
}
