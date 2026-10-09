"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/portal/appointments", label: "Appointments" },
  { href: "/portal/documents", label: "Documents" },
  { href: "/portal/ask", label: "Ask" },
] as const;

/** Section links. Each tab is its own page, so back/forward and bookmarks work. */
export function PortalTabs() {
  const pathname = usePathname();

  return (
    <nav aria-label="Portal sections" className="border-b border-line">
      <ul className="mx-auto flex max-w-4xl gap-2 px-6">
        {TABS.map((tab) => {
          const current = pathname.startsWith(tab.href);
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={current ? "page" : undefined}
                className={
                  "-mb-px inline-block border-b-4 px-4 py-3 text-lg font-medium " +
                  (current
                    ? "border-accent text-accent"
                    : "border-transparent text-muted hover:text-ink")
                }
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
