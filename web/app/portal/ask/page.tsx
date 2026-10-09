import type { Metadata } from "next";

export const metadata: Metadata = { title: "Ask" };

export default function AskPage() {
  return (
    <>
      <h1 className="mb-4 text-3xl font-semibold">Ask</h1>
      <p className="text-lg text-muted">Coming soon.</p>
    </>
  );
}
