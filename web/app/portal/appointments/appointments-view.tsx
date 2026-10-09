"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { StatusMessage, type Status } from "@/components/status-message";
import {
  cancelAppointment,
  getMyAppointments,
  isRetryable,
  isStatus,
  messageFor,
  type Appointment,
} from "@/lib/appointments";
import { formatDate, formatTime } from "@/lib/time";
import { useApi } from "@/lib/use-api";
import { AppointmentCard } from "./appointment-card";

const bookButton =
  "inline-flex min-h-11 items-center rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-hover";

export function AppointmentsView() {
  const router = useRouter();
  const params = useSearchParams();
  const upcoming = useApi("upcoming", () => getMyAppointments("upcoming"));
  const past = useApi("past", () => getMyAppointments("past"));

  const [status, setStatus] = useState<Status>(null);
  const [target, setTarget] = useState<Appointment | null>(null);
  const [pending, setPending] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);

  // After booking/rescheduling we arrive with ?booked=<id> or ?rescheduled=<id>.
  // The message is built from the freshly loaded appointment, never guessed.
  const arrivedId = params.get("booked") ?? params.get("rescheduled");
  const arrived = arrivedId ? upcoming.data?.find((a) => a.id === arrivedId) : undefined;
  const arrivalStatus: Status = arrived
    ? {
        kind: "success",
        text: `${params.has("booked") ? "Booked" : "Rescheduled"}: ${arrived.visit_type} with ${arrived.doctor_name} on ${formatDate(arrived.start_at)} at ${formatTime(arrived.start_at)}.`,
      }
    : null;

  function closeDialog() {
    setTarget(null);
    opener.current?.focus();
  }

  async function confirmCancel() {
    if (!target) return;
    setPending(true);
    try {
      await cancelAppointment(target.id);
      setStatus({ kind: "success", text: "Appointment cancelled." });
    } catch (error) {
      if (isStatus(error, 401)) return router.replace("/login");
      setStatus({ kind: "error", text: messageFor(error) });
    } finally {
      setPending(false);
      setTarget(null);
      opener.current = null; // its card may be gone; focus goes to the message
      router.replace("/portal/appointments"); // drop any ?booked= notice
      upcoming.reload();
      past.reload();
    }
  }

  const loadError = upcoming.error ?? past.error;
  const shown: Status =
    status ??
    (loadError
      ? {
          kind: "error",
          text: messageFor(loadError),
          onRetry: isRetryable(loadError)
            ? () => {
                upcoming.reload();
                past.reload();
              }
            : undefined,
        }
      : arrivalStatus);

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-semibold">Your appointments</h1>
        <Link href="/portal/appointments/book" className={bookButton}>
          Book a visit
        </Link>
      </div>

      <StatusMessage status={shown} focus />

      <section aria-labelledby="upcoming-heading" className="mb-10">
        <h2 id="upcoming-heading" className="mb-4 text-2xl font-semibold">
          Upcoming
        </h2>
        {!upcoming.data ? (
          <p className="text-muted">{upcoming.loading ? "Loading…" : ""}</p>
        ) : upcoming.data.length === 0 ? (
          <div className="flex flex-wrap items-center gap-4">
            <p className="text-muted">No upcoming appointments.</p>
            <Link href="/portal/appointments/book" className={bookButton}>
              Book a visit
            </Link>
          </div>
        ) : (
          <ul className="flex flex-col gap-4">
            {upcoming.data.map((a) => (
              <AppointmentCard
                key={a.id}
                appointment={a}
                onCancel={(appt, button) => {
                  opener.current = button;
                  setStatus(null);
                  setTarget(appt);
                }}
              />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="past-heading">
        <h2 id="past-heading" className="mb-4 text-2xl font-semibold">
          Past
        </h2>
        {!past.data ? (
          <p className="text-muted">{past.loading ? "Loading…" : ""}</p>
        ) : past.data.length === 0 ? (
          <p className="text-muted">No past visits.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {past.data.map((a) => (
              <AppointmentCard key={a.id} appointment={a} />
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={target !== null}
        message={
          target
            ? `Cancel your ${target.visit_type} on ${formatDate(target.start_at)} at ${formatTime(target.start_at)}?`
            : ""
        }
        cancelLabel="Keep appointment"
        confirmLabel="Cancel appointment"
        pending={pending}
        onConfirm={confirmCancel}
        onClose={closeDialog}
      />
    </>
  );
}
