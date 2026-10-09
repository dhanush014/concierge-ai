import { ApiError, apiFetch } from "@/lib/api";
import { addDays, clinicMidnight } from "@/lib/time";

export type Doctor = {
  id: string;
  name: string;
  specialty: string;
  visit_types: string[];
};

export type Slot = {
  id: string;
  doctor_id: string;
  start_at: string; // UTC ISO
  end_at: string;
  visit_type: string;
};

export type Appointment = {
  id: string;
  status: "booked" | "cancelled";
  created_at: string;
  slot_id: string;
  start_at: string;
  end_at: string;
  visit_type: string;
  doctor_id: string;
  doctor_name: string;
  specialty: string;
};

export const WINDOW_DAYS = 14;

export function getDoctors(): Promise<Doctor[]> {
  return apiFetch<Doctor[]>("/doctors");
}

/** Open slots for one doctor and visit type, for the 14 clinic days starting at `from`. */
export function getSlots(doctorId: string, visitType: string, from: string): Promise<Slot[]> {
  const query = new URLSearchParams({
    doctor_id: doctorId,
    visit_type: visitType,
    date_from: clinicMidnight(from).toISOString(),
    date_to: clinicMidnight(addDays(from, WINDOW_DAYS)).toISOString(),
  });
  return apiFetch<Slot[]>(`/slots?${query}`);
}

export function getMyAppointments(when: "upcoming" | "past"): Promise<Appointment[]> {
  return apiFetch<Appointment[]>(`/me/appointments?when=${when}`);
}

export function bookSlot(slotId: string): Promise<Appointment> {
  return apiFetch<Appointment>("/appointments", {
    method: "POST",
    body: JSON.stringify({ slot_id: slotId }),
  });
}

export function cancelAppointment(id: string): Promise<Appointment> {
  return apiFetch<Appointment>(`/appointments/${id}/cancel`, { method: "POST" });
}

export function rescheduleAppointment(id: string, newSlotId: string): Promise<Appointment> {
  return apiFetch<Appointment>(`/appointments/${id}/reschedule`, {
    method: "POST",
    body: JSON.stringify({ new_slot_id: newSlotId }),
  });
}

export const SLOT_TAKEN_MESSAGE = "Sorry, someone just booked that time. Please pick another.";
export const GENERIC_MESSAGE = "Something went wrong. Please try again.";

const REASONS_400: Record<string, string> = {
  slot_in_past: "That time has already passed.",
  appointment_in_past: "That appointment has already happened.",
  slot_mismatch: "That time is for a different doctor or visit type.",
  same_slot: "That is already your appointment time.",
};

/** Plain-language message for a failed API call. */
export function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_MESSAGE;
  switch (error.status) {
    case 400:
      return REASONS_400[error.detail] ?? "That change isn't allowed.";
    case 403:
      return "You can't change this appointment.";
    case 404:
      return "That appointment or time no longer exists.";
    case 409:
      return error.detail === "appointment_not_booked"
        ? "This appointment was already cancelled."
        : SLOT_TAKEN_MESSAGE;
    default:
      return GENERIC_MESSAGE;
  }
}

/** 500s and network failures: worth a Retry button. */
export function isRetryable(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
}

export function isStatus(error: unknown, status: number): boolean {
  return error instanceof ApiError && error.status === status;
}
