"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { SlotPicker } from "@/components/slot-picker";
import { StatusMessage, type Status } from "@/components/status-message";
import {
  SLOT_TAKEN_MESSAGE,
  getSlots,
  isRetryable,
  isStatus,
  messageFor,
  type Slot,
} from "@/lib/appointments";
import { isYmd, todayInClinic } from "@/lib/time";
import { hrefWith } from "@/lib/url";
import { useApi } from "@/lib/use-api";

type Props = {
  basePath: string;
  /** Query params that must be kept in every URL of this flow (e.g. doctor, type). */
  keep: Record<string, string>;
  doctorId: string;
  visitType: string;
  timeHeading: string;
  reviewHeading: string;
  renderReview: (slot: Slot) => ReactNode;
  confirmLabel: string;
  /** Performs the booking; returns the URL to go to on success. */
  submit: (slotId: string) => Promise<string>;
};

/**
 * The shared "choose a time" + "review" steps for booking and rescheduling.
 * The 2-week window (?from=) and the chosen slot (?slot=) live in the URL.
 */
export function SlotFlow(props: Props) {
  const { basePath, keep, doctorId, visitType, submit } = props;
  const router = useRouter();
  const params = useSearchParams();
  const today = todayInClinic();
  const fromParam = params.get("from");
  const from = isYmd(fromParam) && fromParam > today ? fromParam : today; // never before today
  const slotId = params.get("slot");

  const slots = useApi(`slots:${doctorId}:${visitType}:${from}`, () => getSlots(doctorId, visitType, from));
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [pending, setPending] = useState(false);

  const slot = slotId ? slots.data?.find((s) => s.id === slotId) : undefined;
  const slotGone = Boolean(slotId && slots.data && !slots.loading && !slot);
  const href = (values: Record<string, string | null>) =>
    hrefWith(basePath, { ...keep, from: from === today ? null : from, ...values });

  async function confirm() {
    if (!slot) return;
    setPending(true);
    setStatus(null);
    try {
      router.push(await submit(slot.id)); // stays pending: we're leaving the page
    } catch (error) {
      setPending(false);
      if (isStatus(error, 401)) return router.replace("/login");
      if (isRetryable(error)) {
        setStatus({ kind: "error", text: messageFor(error), onRetry: confirm });
        return;
      }
      // 409 taken, 404 gone, 400 not allowed, 403: back to the time step with fresh slots.
      setStatus({ kind: "error", text: messageFor(error) });
      setSelected(null);
      slots.reload();
      router.replace(href({ slot: null }), { scroll: false });
    }
  }

  if (slot) {
    return (
      <section aria-labelledby="review-heading">
        <h2 id="review-heading" className="mb-4 text-2xl font-semibold">
          {props.reviewHeading}
        </h2>
        <StatusMessage status={status} focus />
        {props.renderReview(slot)}
        <div className="mt-8 flex flex-wrap gap-3">
          <button
            type="button"
            disabled={pending}
            onClick={confirm}
            className="min-h-11 rounded-md bg-accent px-6 text-lg font-semibold text-white hover:bg-accent-hover disabled:opacity-60"
          >
            {pending ? "Saving…" : props.confirmLabel}
          </button>
          <Link
            href={href({ slot: null })}
            className="inline-flex min-h-11 items-center rounded-md border border-accent px-5 font-medium text-accent"
          >
            Back
          </Link>
        </div>
      </section>
    );
  }

  const shown: Status =
    status ??
    (slotGone
      ? { kind: "error", text: SLOT_TAKEN_MESSAGE }
      : slots.error
        ? {
            kind: "error",
            text: messageFor(slots.error),
            onRetry: isRetryable(slots.error) ? slots.reload : undefined,
          }
        : null);

  return (
    <section aria-labelledby="time-heading">
      <h2 id="time-heading" className="mb-4 text-2xl font-semibold">
        {props.timeHeading}
      </h2>
      <StatusMessage status={shown} focus />
      <SlotPicker
        from={from}
        today={today}
        slots={slots.data}
        loading={slots.loading}
        selectedId={selected}
        onSelect={(id) => {
          setSelected(id);
          setStatus(null);
        }}
        onWindow={(next) => {
          setSelected(null);
          router.push(href({ from: next === today ? null : next, slot: null }), { scroll: false });
        }}
        onContinue={() => selected && router.push(href({ slot: selected }))}
      />
    </section>
  );
}

/** Label/value rows for the review step. */
export function ReviewList({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-3 rounded-lg border border-line p-5 text-lg">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted">{label}</dt>
          <dd className="font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
