"use client";

import { useId, useRef, useState, type DragEvent } from "react";
import {
  ACCEPT,
  KIND_LABEL,
  checkFile,
  formatBytes,
  messageFor,
  uploadDocument,
  type DocumentKind,
  type PatientDocument,
} from "@/lib/documents";
import { isStatus } from "@/lib/api";

type Props = {
  kind: DocumentKind;
  onUploaded: (doc: PatientDocument) => void;
  onCancel: () => void;
  onUnauthorized: () => void;
};

/** File picker + drop zone. Shows the chosen file before uploading. */
export function Uploader({ kind, onUploaded, onCancel, onUnauthorized }: Props) {
  const inputId = useId();
  const errorId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [dragging, setDragging] = useState(false);

  function choose(chosen: File | undefined) {
    if (!chosen) return;
    setFile(chosen);
    setError(checkFile(chosen));
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    choose(e.dataTransfer.files[0]);
  }

  async function upload() {
    if (!file) return;
    setPending(true);
    setError(null);
    try {
      onUploaded(await uploadDocument(file, kind));
    } catch (err) {
      if (isStatus(err, 401)) return onUnauthorized();
      setError(messageFor(err));
      setPending(false);
    }
  }

  return (
    <section aria-labelledby={`${inputId}-heading`} className="mb-8 rounded-lg border border-line p-5">
      <h2 id={`${inputId}-heading`} className="mb-4 text-xl font-semibold">
        Upload {KIND_LABEL[kind].toLowerCase()}
      </h2>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDragEnter={() => setDragging(true)}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="drop-zone"
        className={
          "flex flex-col items-center gap-3 rounded-md border-2 border-dashed px-4 py-8 text-center " +
          (dragging ? "border-accent bg-accent-soft" : "border-line")
        }
      >
        <p className="text-muted">Drag a file here, or</p>
        <input
          ref={input}
          id={inputId}
          type="file"
          accept={ACCEPT}
          className="peer sr-only"
          aria-describedby={error ? errorId : undefined}
          onChange={(e) => choose(e.target.files?.[0])}
        />
        <label
          htmlFor={inputId}
          className="inline-flex min-h-11 cursor-pointer items-center rounded-md border border-accent px-5 font-medium text-accent hover:bg-accent-soft peer-focus-visible:outline peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent"
        >
          Choose file
        </label>
        <p className="text-sm text-muted">JPEG, PNG, or PDF, up to 10 MB. On a phone you can take a photo.</p>
      </div>

      {file && (
        <p className="mt-4 text-lg">
          <span className="font-medium">{file.name}</span> · {formatBytes(file.size)}
        </p>
      )}
      <p id={errorId} role="alert" className="mt-2 min-h-[1.6em] font-medium text-danger">
        {error}
      </p>

      <div className="mt-2 flex flex-wrap gap-3">
        <button
          type="button"
          disabled={!file || error !== null || pending}
          onClick={upload}
          className="min-h-11 rounded-md bg-accent px-6 font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
        >
          {pending ? "Uploading…" : "Upload"}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={onCancel}
          className="min-h-11 rounded-md border border-accent px-5 font-medium text-accent"
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
