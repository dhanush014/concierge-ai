"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { StatusMessage } from "@/components/status-message";
import { getMyAppointments, isRetryable, messageFor, rescheduleAppointment } from "@/lib/appointments";
import { formatDateTime } from "@/lib/time";
import { useApi } from "@/lib/use-api";
import { ReviewList, SlotFlow } from "../../slot-flow";

/** Pick a new time for the same doctor and visit type, review "From -> To", confirm. */
export function RescheduleFlow() {
  const { id } = useParams<{ id: string }>();
  const upcoming = useApi("upcoming", () => getMyAppointments("upcoming"));
  const appt = upcoming.data?.find((a) => a.id === id);

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-semibold">Reschedule</h1>
        <Link href="/portal/appointments" className="font-medium text-accent underline">
          Back to your appointments
        </Link>
      </div>

      {upcoming.error ? (
        <StatusMessage
          status={{
            kind: "error",
            text: messageFor(upcoming.error),
            onRetry: isRetryable(upcoming.error) ? upcoming.reload : undefined,
          }}
          focus
        />
      ) : !upcoming.data ? (
        <p className="text-muted">Loading…</p>
      ) : !appt ? (
        <StatusMessage
          status={{ kind: "error", text: "That appointment or time no longer exists." }}
          focus
        />
      ) : (
        <>
          <div className="mb-8 rounded-lg border border-line p-5">
            <p className="text-muted">Current appointment</p>
            <p className="text-lg font-semibold">{formatDateTime(appt.start_at)}</p>
            <p>
              {appt.doctor_name} · {appt.specialty}
            </p>
            <p className="text-muted">{appt.visit_type}</p>
          </div>
          <SlotFlow
            basePath={`/portal/appointments/${appt.id}/reschedule`}
            keep={{}}
            doctorId={appt.doctor_id}
            visitType={appt.visit_type}
            timeHeading="Choose a new time"
            reviewHeading="Review the change"
            confirmLabel="Confirm new time"
            renderReview={(slot) => (
              <ReviewList
                rows={[
                  ["From", formatDateTime(appt.start_at)],
                  ["To", formatDateTime(slot.start_at)],
                  ["Doctor", `${appt.doctor_name} · ${appt.specialty}`],
                  ["Visit type", appt.visit_type],
                ]}
              />
            )}
            submit={async (slotId) =>
              `/portal/appointments?rescheduled=${(await rescheduleAppointment(appt.id, slotId)).id}`
            }
          />
        </>
      )}
    </>
  );
}
