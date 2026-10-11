import type { Metadata } from "next";
import { Suspense } from "react";
import { HandoffView } from "./handoff-view";

export const metadata: Metadata = { title: "Handoff" };

export default function HandoffPage({ params }: PageProps<"/staff/handoffs/[id]">) {
  // Reading the URL params inside Suspense keeps navigation from the inbox instant.
  return (
    <Suspense fallback={<p className="text-muted">Loading…</p>}>
      <Ticket params={params} />
    </Suspense>
  );
}

async function Ticket({ params }: { params: PageProps<"/staff/handoffs/[id]">["params"] }) {
  const { id } = await params;
  return <HandoffView id={id} />;
}
