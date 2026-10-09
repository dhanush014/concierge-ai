import { ApiError, apiFetch } from "@/lib/api";

export type DocumentKind = "insurance_card" | "referral";

export type PatientDocument = {
  id: string;
  kind: DocumentKind;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
};

export const KIND_LABEL: Record<DocumentKind, string> = {
  insurance_card: "Insurance card",
  referral: "Referral",
};

export const MAX_BYTES = 10 * 1024 * 1024;
export const ACCEPT = "image/*,application/pdf"; // image/* lets phones offer the camera
const ALLOWED_TYPES = ["image/jpeg", "image/png", "application/pdf"];

export const TYPE_MESSAGE = "That file type isn't supported. Please upload a JPEG, PNG, or PDF.";
export const SIZE_MESSAGE = "That file is too large. The limit is 10 MB.";
export const EMPTY_MESSAGE = "That file is empty. Please choose another.";

export function listDocuments(): Promise<PatientDocument[]> {
  return apiFetch<PatientDocument[]>("/me/documents");
}

export function uploadDocument(file: File, kind: DocumentKind): Promise<PatientDocument> {
  const body = new FormData();
  body.append("file", file);
  body.append("kind", kind);
  return apiFetch<PatientDocument>("/me/documents", { method: "POST", body });
}

export function getDocumentUrl(id: string): Promise<{ url: string; expires_in: number }> {
  return apiFetch(`/me/documents/${id}/url`);
}

export function deleteDocument(id: string): Promise<void> {
  return apiFetch<void>(`/me/documents/${id}`, { method: "DELETE" });
}

/** Quick check before uploading. The server checks the real bytes again. */
export function checkFile(file: File): string | null {
  if (file.size === 0) return EMPTY_MESSAGE;
  if (file.size > MAX_BYTES) return SIZE_MESSAGE;
  if (file.type && !ALLOWED_TYPES.includes(file.type)) return TYPE_MESSAGE;
  return null;
}

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === "unsupported_type") return TYPE_MESSAGE;
    if (error.detail === "empty_file") return EMPTY_MESSAGE;
    if (error.status === 413) return SIZE_MESSAGE;
    if (error.status === 404) return "That document no longer exists.";
    if (error.status === 403) return "You can't change this document.";
  }
  return "Something went wrong. Please try again.";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
