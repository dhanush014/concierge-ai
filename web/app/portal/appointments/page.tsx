import type { Metadata } from "next";

export const metadata: Metadata = { title: "Appointments" };

// Built in the next step.
export default function AppointmentsPage() {
  return (
    <>
      <h1 className="mb-4 text-3xl font-semibold">Appointments</h1>
      <p className="text-lg text-muted">Your appointments will appear here.</p>
    </>
  );
}
