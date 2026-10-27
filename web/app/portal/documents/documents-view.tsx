"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { StatusMessage, type Status } from "@/components/status-message";
import { isRetryable, isStatus } from "@/lib/api";
import {
  KIND_LABEL,
  deleteDocument,
  getDocumentUrl,
  listDocuments,
  messageFor,
  type DocumentKind,
  type PatientDocument,
} from "@/lib/documents";
import {
  NETWORK,
  confirmInsurance,
  getMyInsurance,
  messageFor as insuranceMessage,
  readCard,
  type CardFields,
  type Insurance,
} from "@/lib/insurance";
import { useApi } from "@/lib/use-api";
import { CardForm } from "./card-form";
import { DocumentRow } from "./document-row";
import { InsuranceSummary } from "./insurance-summary";
import { Uploader } from "./uploader";

const KINDS: DocumentKind[] = ["insurance_card", "referral"];

export function DocumentsView() {
  const router = useRouter();
  const docs = useApi("documents", listDocuments);
  const insurance = useApi("insurance", getMyInsurance);
  // The card being read (button busy), then what was read (the form).
  const [readingId, setReadingId] = useState<string | null>(null);
  const [read, setRead] = useState<{ insurance: Insurance; filename: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [uploadKind, setUploadKind] = useState<DocumentKind | null>(null);
  const [target, setTarget] = useState<PatientDocument | null>(null);
  const [pending, setPending] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);

  const toLogin = () => router.replace("/login");

  async function view(doc: PatientDocument) {
    // Open the tab now, inside the click, so popup blockers allow it; fill it in once signed.
    const tab = window.open("", "_blank");
    try {
      const { url } = await getDocumentUrl(doc.id);
      if (tab) {
        tab.opener = null;
        tab.location.href = url;
      } else {
        window.location.href = url;
      }
    } catch (error) {
      tab?.close();
      if (isStatus(error, 401)) return toLogin();
      setStatus({ kind: "error", text: messageFor(error) });
      if (isStatus(error, 404)) docs.reload();
    }
  }

  async function readCardOf(doc: PatientDocument) {
    setStatus(null);
    setRead(null);
    setReadingId(doc.id);
    try {
      setRead({ insurance: await readCard(doc.id), filename: doc.original_filename });
    } catch (error) {
      if (isStatus(error, 401)) return toLogin();
      setStatus({
        kind: "error",
        text: insuranceMessage(error),
        onRetry: isRetryable(error) ? () => readCardOf(doc) : undefined,
      });
    } finally {
      setReadingId(null);
    }
  }

  async function confirmCard(fields: CardFields) {
    if (!read) return;
    setSaving(true);
    try {
      const saved = await confirmInsurance(read.insurance.id, fields);
      setRead(null);
      setStatus({ kind: "success", text: `Saved: ${saved.payer}. ${NETWORK[saved.network].label}.` });
      insurance.reload();
    } catch (error) {
      if (isStatus(error, 401)) return toLogin();
      setStatus({ kind: "error", text: insuranceMessage(error) });
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!target) return;
    setPending(true);
    try {
      await deleteDocument(target.id);
      setStatus({ kind: "success", text: "Document deleted." });
    } catch (error) {
      if (isStatus(error, 401)) return toLogin();
      setStatus({ kind: "error", text: messageFor(error) });
    } finally {
      setPending(false);
      setTarget(null);
      opener.current = null; // its row may be gone; focus goes to the message
      docs.reload();
      insurance.reload(); // deleting a card deletes the insurance read from it
    }
  }

  const shown: Status =
    status ??
    (docs.error
      ? {
          kind: "error",
          text: messageFor(docs.error),
          onRetry: isRetryable(docs.error) ? docs.reload : undefined,
        }
      : null);

  return (
    <>
      <h1 className="mb-6 text-3xl font-semibold">Your documents</h1>

      <InsuranceSummary insurance={insurance.error ? null : insurance.data} />

      <div className="mb-6 flex flex-wrap gap-3">
        {KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            aria-expanded={uploadKind === kind}
            onClick={() => {
              setStatus(null);
              setUploadKind(kind);
            }}
            className="min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-hover"
          >
            Upload {KIND_LABEL[kind].toLowerCase()}
          </button>
        ))}
      </div>

      <StatusMessage status={shown} focus />

      {read && (
        <CardForm
          key={read.insurance.id}
          reading={read.insurance}
          filename={read.filename}
          pending={saving}
          onConfirm={confirmCard}
          onCancel={() => setRead(null)}
        />
      )}

      {uploadKind && (
        <Uploader
          key={uploadKind}
          kind={uploadKind}
          onCancel={() => setUploadKind(null)}
          onUnauthorized={toLogin}
          onUploaded={(doc) => {
            setUploadKind(null);
            setStatus({ kind: "success", text: `Uploaded: ${doc.original_filename}.` });
            docs.reload();
          }}
        />
      )}

      {!docs.data ? (
        <p className="text-muted">{docs.loading ? "Loading…" : ""}</p>
      ) : docs.data.length === 0 ? (
        <p className="text-muted">No documents yet.</p>
      ) : (
        <ul className="flex flex-col gap-4" aria-label="Your documents">
          {docs.data.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              onView={view}
              onRead={readCardOf}
              reading={readingId === doc.id}
              onDelete={(d, button) => {
                opener.current = button;
                setStatus(null);
                setTarget(d);
              }}
            />
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={target !== null}
        message={target ? `Delete ${target.original_filename}? This can't be undone.` : ""}
        cancelLabel="Keep document"
        confirmLabel="Delete document"
        pendingLabel="Deleting…"
        pending={pending}
        onConfirm={confirmDelete}
        onClose={() => {
          setTarget(null);
          opener.current?.focus();
        }}
      />
    </>
  );
}
