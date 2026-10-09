"use client";

import Link from "next/link";
import type { MouseEvent } from "react";
import type { Appointment } from "@/lib/appointments";
import { formatDateTime } from "@/lib/time";

type Props = {
  appointment: Appointment;
  /** Only upcoming appointments get actions. */
  onCancel?: (appointment: Appointment, opener: HTMLButtonElement) => void;
};

export function AppointmentCard({ appointment: a, onCancel }: Props) {
  const when = formatDateTime(a.start_at);
  return (
    <li className="flex flex-wrap items-end justify-between gap-4 rounded-lg border border-line p-5">
      <div>
        <p className="text-lg font-semibold">{when}</p>
        <p>
          {a.doctor_name} · {a.specialty}
        </p>
        <p className="text-muted">{a.visit_type}</p>
      </div>
      {onCancel && (
        <div className="flex gap-3">
          <Link
            href={`/portal/appointments/${a.id}/reschedule`}
            aria-label={`Reschedule ${a.visit_type} on ${when}`}
            className="inline-flex min-h-11 items-center rounded-md border border-accent px-4 font-medium text-accent hover:bg-accent-soft"
          >
            Reschedule
          </Link>
          <button
            type="button"
            aria-label={`Cancel ${a.visit_type} on ${when}`}
            onClick={(e: MouseEvent<HTMLButtonElement>) => onCancel(a, e.currentTarget)}
            className="min-h-11 rounded-md border border-danger px-4 font-medium text-danger hover:bg-red-50"
          >
            Cancel
          </button>
        </div>
      )}
    </li>
  );
}
