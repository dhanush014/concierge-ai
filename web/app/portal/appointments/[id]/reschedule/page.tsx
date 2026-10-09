import type { Metadata } from "next";
import { Suspense } from "react";
import { RescheduleFlow } from "./reschedule-flow";

export const metadata: Metadata = { title: "Reschedule" };

export default function ReschedulePage() {
  return (
    <Suspense fallback={<p className="text-muted">Loading…</p>}>
      <RescheduleFlow />
    </Suspense>
  );
}
