"use client";

import type { MouseEvent } from "react";
import { KIND_LABEL, formatBytes, type PatientDocument } from "@/lib/documents";
import { CARD_IMAGE_TYPES } from "@/lib/insurance";
import { formatDate } from "@/lib/time";

type Props = {
  doc: PatientDocument;
  onView: (doc: PatientDocument) => void;
  onDelete: (doc: PatientDocument, opener: HTMLButtonElement) => void;
  /** Insurance-card photos only: read the card with the AI. */
  onRead?: (doc: PatientDocument) => void;
  reading?: boolean;
};

export function DocumentRow({ doc, onView, onDelete, onRead, reading = false }: Props) {
  const readable = doc.kind === "insurance_card" && CARD_IMAGE_TYPES.includes(doc.content_type);
  const name = doc.original_filename;
  return (
    <li className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-line p-5">
      <div className="min-w-0">
        <p className="text-lg">
          <span className="font-semibold">{KIND_LABEL[doc.kind]}</span> ·{" "}
          <span className="[overflow-wrap:anywhere]">{name}</span>
        </p>
        <p className="text-muted">
          {formatDate(doc.created_at)} · {formatBytes(doc.size_bytes)}
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        {readable && onRead && (
          <button
            type="button"
            aria-label={`Read card ${name}`}
            onClick={() => onRead(doc)}
            disabled={reading}
            className="min-h-11 rounded-md bg-accent px-4 font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {reading ? "Reading…" : "Read card"}
          </button>
        )}
        <button
          type="button"
          aria-label={`View ${name} (opens in a new tab)`}
          onClick={() => onView(doc)}
          className="min-h-11 rounded-md border border-accent px-4 font-medium text-accent hover:bg-accent-soft"
        >
          View
        </button>
        <button
          type="button"
          aria-label={`Delete ${name}`}
          onClick={(e: MouseEvent<HTMLButtonElement>) => onDelete(doc, e.currentTarget)}
          className="min-h-11 rounded-md border border-danger px-4 font-medium text-danger hover:bg-red-50"
        >
          Delete
        </button>
      </div>
    </li>
  );
}
