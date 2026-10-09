"use client";

import type { Slot } from "@/lib/appointments";
import { WINDOW_DAYS } from "@/lib/appointments";
import { addDays, clinicDate, formatDayHeading, formatTime } from "@/lib/time";

type Props = {
  from: string; // first clinic day shown, YYYY-MM-DD
  today: string;
  slots: Slot[] | undefined;
  loading: boolean;
  selectedId: string | null;
  onSelect: (slotId: string) => void;
  onWindow: (from: string) => void;
  onContinue: () => void;
};

/** 14 clinic days of open slots, grouped by day, with paging that never goes before today. */
export function SlotPicker({ from, today, slots, loading, selectedId, onSelect, onWindow, onContinue }: Props) {
  const days = Array.from({ length: WINDOW_DAYS }, (_, i) => addDays(from, i));
  const byDay = new Map<string, Slot[]>();
  for (const slot of slots ?? []) {
    const day = clinicDate(slot.start_at);
    byDay.set(day, [...(byDay.get(day) ?? []), slot]);
  }
  const atStart = from <= today;
  const last = days[days.length - 1];

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="font-medium">
          {formatDayHeading(from)} – {formatDayHeading(last)}
        </p>
        <div className="flex gap-3">
          <button
            type="button"
            disabled={atStart}
            onClick={() => onWindow(addDays(from, -WINDOW_DAYS) < today ? today : addDays(from, -WINDOW_DAYS))}
            className="min-h-11 rounded-md border border-accent px-4 font-medium text-accent disabled:border-line disabled:text-muted"
          >
            Previous 2 weeks
          </button>
          <button
            type="button"
            onClick={() => onWindow(addDays(from, WINDOW_DAYS))}
            className="min-h-11 rounded-md border border-accent px-4 font-medium text-accent"
          >
            Next 2 weeks
          </button>
        </div>
      </div>

      {loading && !slots ? (
        <p className="text-muted">Loading times…</p>
      ) : (
        <ol className="flex flex-col gap-6">
          {days.map((day) => {
            const daySlots = byDay.get(day) ?? [];
            const headingId = `day-${day}`;
            return (
              <li key={day} aria-labelledby={headingId}>
                <h3 id={headingId} className="mb-2 font-semibold">
                  {formatDayHeading(day)}
                </h3>
                {daySlots.length === 0 ? (
                  <p className="text-muted">No openings</p>
                ) : (
                  <ul className="flex flex-wrap gap-2">
                    {daySlots.map((slot) => {
                      const selected = slot.id === selectedId;
                      return (
                        <li key={slot.id}>
                          <button
                            type="button"
                            aria-pressed={selected}
                            aria-label={`${formatDayHeading(day)}, ${formatTime(slot.start_at)}`}
                            onClick={() => onSelect(slot.id)}
                            className={
                              "min-h-11 rounded-md px-4 font-medium " +
                              (selected
                                ? "border-[3px] border-accent bg-accent-soft text-accent-hover"
                                : "border border-line hover:border-accent")
                            }
                          >
                            {selected && <span aria-hidden="true">✓ </span>}
                            {formatTime(slot.start_at)}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ol>
      )}

      <div className="sticky bottom-0 mt-8 border-t border-line bg-white py-4">
        <button
          type="button"
          disabled={!selectedId}
          onClick={onContinue}
          className="min-h-11 rounded-md bg-accent px-6 text-lg font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
        >
          Continue
        </button>
      </div>
    </div>
  );
}
