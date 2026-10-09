import type { ReactNode } from "react";

/** Top bar with the hospital name. `children` go on the right (e.g. account + sign out). */
export function SiteHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-4 px-6 py-5">
        <p className="text-2xl font-semibold tracking-tight text-accent">Riverside Health</p>
        {children}
      </div>
    </header>
  );
}
