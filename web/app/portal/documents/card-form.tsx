"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { FIELD_LABEL, FIELD_ORDER, NETWORK, type CardFields, type Insurance } from "@/lib/insurance";
import { NetworkBadge } from "./insurance-summary";

type Props = {
  reading: Insurance; // what the AI read off the card
  filename: string;
  pending: boolean;
  onConfirm: (fields: CardFields) => void;
  onCancel: () => void;
};

/**
 * What was read off the card, editable. Fields the AI couldn't read are empty and
 * highlighted; a name that isn't the patient's gets a warning (confirming is still allowed).
 */
export function CardForm({ reading, filename, pending, onConfirm, onCancel }: Props) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const [fields, setFields] = useState<CardFields>(() =>
    Object.fromEntries(FIELD_ORDER.map((f) => [f, reading[f] ?? ""])) as CardFields,
  );
  const unread = FIELD_ORDER.filter((f) => !reading[f]);

  useEffect(() => heading.current?.focus(), []); // land on the form after Read card

  function submit(e: FormEvent) {
    e.preventDefault();
    onConfirm(Object.fromEntries(FIELD_ORDER.map((f) => [f, fields[f]?.trim() || null])) as CardFields);
  }

  return (
    <section aria-labelledby={`${id}-h`} className="mb-8 rounded-lg border border-accent p-5">
      <h2 id={`${id}-h`} ref={heading} tabIndex={-1} className="mb-1 text-2xl font-semibold outline-none">
        Check your card details
      </h2>
      <p className="mb-4 text-muted">
        Read from {filename}. Fix anything that doesn&apos;t match your card, then confirm.
      </p>

      {unread.length > 0 && (
        <p className="mb-4 rounded-md border-l-4 border-warn bg-warn-soft px-4 py-3 font-medium text-warn">
          We couldn&apos;t read {unread.length === 1 ? "one field" : `${unread.length} fields`}. Please type{" "}
          {unread.length === 1 ? "it" : "them"} from your card.
        </p>
      )}
      {reading.name_warning && (
        <p role="alert" className="mb-4 rounded-md border-l-4 border-danger bg-danger-soft px-4 py-3 font-medium text-danger">
          {reading.name_warning}
        </p>
      )}

      <form onSubmit={submit} className="flex flex-col gap-4">
        {FIELD_ORDER.map((f) => {
          const missing = !reading[f];
          return (
            <div key={f}>
              <label htmlFor={`${id}-${f}`} className="mb-1 block font-medium">
                {FIELD_LABEL[f]}
                {f === "payer" && <span className="text-muted"> (required)</span>}
              </label>
              <input
                id={`${id}-${f}`}
                value={fields[f] ?? ""}
                onChange={(e) => setFields((v) => ({ ...v, [f]: e.target.value }))}
                required={f === "payer"}
                maxLength={200}
                aria-describedby={missing ? `${id}-${f}-note` : undefined}
                className={`min-h-11 w-full rounded-md border px-4 py-2 text-lg ${
                  missing ? "border-2 border-warn bg-warn-soft" : "border-line"
                }`}
              />
              {missing && (
                <p id={`${id}-${f}-note`} className="mt-1 text-warn">
                  Couldn&apos;t read this. Please type it from your card.
                </p>
              )}
            </div>
          );
        })}

        <div className="flex flex-wrap items-center gap-3">
          <span className="text-muted">As read:</span>
          <NetworkBadge status={reading.network} />
          <span className="text-muted">{NETWORK[reading.network].detail}</span>
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="submit"
            disabled={pending}
            className="min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {pending ? "Saving…" : "Confirm"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="min-h-11 rounded-md border border-line px-5 font-medium hover:border-accent"
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
