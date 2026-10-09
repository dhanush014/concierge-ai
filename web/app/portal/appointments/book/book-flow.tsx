"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { StatusMessage } from "@/components/status-message";
import { bookSlot, getDoctors, isRetryable, messageFor, type Doctor } from "@/lib/appointments";
import { formatDate, formatTime } from "@/lib/time";
import { hrefWith } from "@/lib/url";
import { useApi } from "@/lib/use-api";
import { ReviewList, SlotFlow } from "../slot-flow";

const BASE = "/portal/appointments/book";
const card =
  "block min-h-11 rounded-lg border border-line p-5 hover:border-accent hover:bg-accent-soft";

/** Step 1 doctor -> 2 visit type -> 3 time -> 4 review. Every choice is in the URL. */
export function BookFlow() {
  const router = useRouter();
  const params = useSearchParams();
  const doctors = useApi("doctors", getDoctors);

  const doctor = doctors.data?.find((d) => d.id === params.get("doctor")) ?? null;
  const typeParam = params.get("type");
  const visitType = doctor && typeParam && doctor.visit_types.includes(typeParam) ? typeParam : null;
  const onlyType = doctor && !typeParam && doctor.visit_types.length === 1 ? doctor.visit_types[0] : null;

  // One visit type: skip step 2 (replace, so Back returns to step 1).
  useEffect(() => {
    if (doctor && onlyType) router.replace(hrefWith(BASE, { doctor: doctor.id, type: onlyType }));
  }, [doctor, onlyType, router]);

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-semibold">Book a visit</h1>
        <Link href="/portal/appointments" className="font-medium text-accent underline">
          Back to your appointments
        </Link>
      </div>

      {doctor && <Choices doctor={doctor} visitType={visitType} />}

      {doctors.error ? (
        <StatusMessage
          status={{
            kind: "error",
            text: messageFor(doctors.error),
            onRetry: isRetryable(doctors.error) ? doctors.reload : undefined,
          }}
          focus
        />
      ) : !doctors.data || onlyType ? (
        <p className="text-muted">Loading…</p>
      ) : !doctor ? (
        <DoctorStep doctors={doctors.data} />
      ) : !visitType ? (
        <TypeStep doctor={doctor} />
      ) : (
        <SlotFlow
          basePath={BASE}
          keep={{ doctor: doctor.id, type: visitType }}
          doctorId={doctor.id}
          visitType={visitType}
          timeHeading="Step 3 of 4: Choose a time"
          reviewHeading="Step 4 of 4: Review"
          confirmLabel="Confirm booking"
          renderReview={(slot) => (
            <ReviewList
              rows={[
                ["Doctor", `${doctor.name} · ${doctor.specialty}`],
                ["Visit type", visitType],
                ["Date", formatDate(slot.start_at)],
                ["Time", formatTime(slot.start_at)],
              ]}
            />
          )}
          submit={async (slotId) => `/portal/appointments?booked=${(await bookSlot(slotId)).id}`}
        />
      )}
    </>
  );
}

function Choices({ doctor, visitType }: { doctor: Doctor; visitType: string | null }) {
  return (
    <ul className="mb-8 flex flex-col gap-1 text-lg" aria-label="Your choices so far">
      <li>
        Doctor: <span className="font-medium">{doctor.name}</span>{" "}
        <Link href={BASE} className="text-accent underline">
          Change<span className="sr-only"> doctor</span>
        </Link>
      </li>
      {visitType && (
        <li>
          Visit type: <span className="font-medium">{visitType}</span>
          {doctor.visit_types.length > 1 && (
            <>
              {" "}
              <Link href={hrefWith(BASE, { doctor: doctor.id })} className="text-accent underline">
                Change<span className="sr-only"> visit type</span>
              </Link>
            </>
          )}
        </li>
      )}
    </ul>
  );
}

function DoctorStep({ doctors }: { doctors: Doctor[] }) {
  return (
    <section aria-labelledby="doctor-heading">
      <h2 id="doctor-heading" className="mb-4 text-2xl font-semibold">
        Step 1 of 4: Choose a doctor
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {doctors.map((d) => (
          <li key={d.id}>
            <Link href={hrefWith(BASE, { doctor: d.id })} className={card}>
              <span className="block text-lg font-semibold">{d.name}</span>
              <span className="text-muted">{d.specialty}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TypeStep({ doctor }: { doctor: Doctor }) {
  return (
    <section aria-labelledby="type-heading">
      <h2 id="type-heading" className="mb-4 text-2xl font-semibold">
        Step 2 of 4: Choose a visit type
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {doctor.visit_types.map((t) => (
          <li key={t}>
            <Link href={hrefWith(BASE, { doctor: doctor.id, type: t })} className={card}>
              <span className="text-lg font-semibold">{t}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
