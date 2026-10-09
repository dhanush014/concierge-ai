import type { Metadata } from "next";

export const metadata: Metadata = { title: "Staff inbox" };

// Live handoff tickets arrive in Phase 3.
export default function StaffPage() {
  return (
    <>
      <h1 className="mb-4 text-3xl font-semibold">Staff inbox</h1>
      <p className="text-lg text-muted">Handoff tickets will appear here. Coming soon.</p>
    </>
  );
}
