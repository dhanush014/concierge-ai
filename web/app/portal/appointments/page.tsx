import type { Metadata } from "next";
import { Suspense } from "react";
import { AppointmentsView } from "./appointments-view";

export const metadata: Metadata = { title: "Appointments" };

export default function AppointmentsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Loading…</p>}>
      <AppointmentsView />
    </Suspense>
  );
}
