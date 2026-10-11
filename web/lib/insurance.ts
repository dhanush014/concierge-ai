import { ApiError, apiFetch } from "@/lib/api";

export type CardFieldName = "payer" | "plan_name" | "member_name" | "member_id" | "group_number";
export type CardFields = Record<CardFieldName, string | null>;
export type NetworkStatus = "in_network" | "out_of_network" | "not_on_file";

export type Insurance = CardFields & {
  id: string;
  document_id: string | null;
  status: "extracted" | "confirmed";
  network: NetworkStatus; // a database lookup, never the AI
  matched_payer: string | null;
  name_warning: string | null;
  created_at: string;
};

export const FIELD_LABEL: Record<CardFieldName, string> = {
  payer: "Insurance company",
  plan_name: "Plan",
  member_name: "Member name",
  member_id: "Member ID",
  group_number: "Group number",
};
export const FIELD_ORDER: CardFieldName[] = ["payer", "plan_name", "member_name", "member_id", "group_number"];

export const NETWORK: Record<NetworkStatus, { label: string; detail: string; tone: string }> = {
  in_network: {
    label: "In network",
    detail: "Riverside Health is in network with this plan.",
    tone: "border-accent bg-accent-soft text-accent-hover",
  },
  out_of_network: {
    label: "Out of network",
    detail: "Riverside Health is not in network with this plan. Visits may cost more.",
    tone: "border-danger bg-danger-soft text-danger",
  },
  not_on_file: {
    label: "Not on file",
    detail: "We don't have this plan on record. Please call billing at 555-0142.",
    tone: "border-warn bg-warn-soft text-warn",
  },
};

export const CARD_IMAGE_TYPES = ["image/jpeg", "image/png"];

/** Read the card with the AI (fields it can't read come back empty). */
export function readCard(documentId: string): Promise<Insurance> {
  return apiFetch<Insurance>(`/me/documents/${encodeURIComponent(documentId)}/extract`, { method: "POST" });
}

export function confirmInsurance(id: string, fields: CardFields): Promise<Insurance> {
  return apiFetch<Insurance>(`/me/insurance/${encodeURIComponent(id)}/confirm`, {
    method: "POST",
    body: JSON.stringify(fields),
  });
}

/** Your confirmed insurance, or null. */
export function getMyInsurance(): Promise<Insurance | null> {
  return apiFetch<Insurance | null>("/me/insurance");
}

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === "extraction_failed") return "We couldn't read the card right now. Please try again.";
    if (error.detail === "not_a_card_image") return "Only photos of an insurance card (JPEG or PNG) can be read.";
    if (error.status === 404) return "That card no longer exists.";
    if (error.status === 422) return "Please fill in the insurance company.";
  }
  return "Something went wrong. Please try again.";
}
