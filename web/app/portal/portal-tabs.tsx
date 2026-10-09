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
  return <TabList pathname={pathname} />;
}

/**
 * The tab bar itself. Rendered with pathname=null as the <Suspense> fallback
 * (on dynamic routes the path is only known at request time).
 */
export function TabList({ pathname }: { pathname: string | null }) {
  return (
    <nav aria-label="Portal sections" className="border-b border-line">
      <ul className="mx-auto flex max-w-4xl gap-1 overflow-x-auto px-3 sm:gap-2 sm:px-6">
        {TABS.map((tab) => {
          const current = pathname?.startsWith(tab.href) ?? false;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={current ? "page" : undefined}
                className={
                  "-mb-px inline-block whitespace-nowrap border-b-4 px-3 py-3 font-medium sm:px-4 sm:text-lg " +
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
