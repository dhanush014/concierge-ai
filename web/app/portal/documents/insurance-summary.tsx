import Link from "next/link";
import { FIELD_LABEL, NETWORK, type Insurance, type NetworkStatus } from "@/lib/insurance";

export function NetworkBadge({ status }: { status: NetworkStatus }) {
  return (
    <span className={`inline-flex rounded-full border-l-4 px-3 py-1 font-semibold ${NETWORK[status].tone}`}>
      {NETWORK[status].label}
    </span>
  );
}

export const COVERAGE_QUESTION = "What is my specialist copay?";

/** The patient's confirmed insurance, or a hint to read a card. */
export function InsuranceSummary({ insurance }: { insurance: Insurance | null | undefined }) {
  return (
    <section aria-labelledby="insurance-heading" className="mb-8 rounded-lg border border-line p-5">
      <h2 id="insurance-heading" className="mb-3 text-2xl font-semibold">
        Your insurance
      </h2>
      {insurance === undefined ? (
        <p className="text-muted">Loading…</p>
      ) : insurance === null ? (
        <p className="text-muted">None saved yet. Upload a photo of your insurance card, then choose Read card.</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <p className="text-lg font-semibold">{insurance.payer}</p>
            <NetworkBadge status={insurance.network} />
          </div>
          <p className="mb-3 text-muted">{NETWORK[insurance.network].detail}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
            {(["plan_name", "member_id", "group_number"] as const).map((f) => (
              <div key={f} className="contents">
                <dt className="text-muted">{FIELD_LABEL[f]}</dt>
                <dd className="[overflow-wrap:anywhere]">{insurance[f] ?? "—"}</dd>
              </div>
            ))}
          </dl>
          <Link
            href={`/portal/ask?c=new&ask=${encodeURIComponent(COVERAGE_QUESTION)}`}
            className="mt-4 inline-flex min-h-11 items-center rounded-md border border-accent px-5 font-semibold text-accent hover:bg-accent-soft"
          >
            Ask about my coverage
          </Link>
        </>
      )}
    </section>
  );
}
