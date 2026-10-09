import { Suspense } from "react";
import { AccountBar } from "@/components/account-bar";
import { RoleGate } from "@/components/role-gate";
import { SiteHeader } from "@/components/site-header";

export default function StaffLayout({ children }: LayoutProps<"/staff">) {
  return (
    <>
      <SiteHeader>
        <Suspense fallback={null}>
          <AccountBar role="staff" />
        </Suspense>
      </SiteHeader>
      <main id="main" className="mx-auto w-full max-w-4xl px-6 py-10">
        <Suspense fallback={<p className="text-muted">Loading…</p>}>
          <RoleGate role="staff">{children}</RoleGate>
        </Suspense>
      </main>
    </>
  );
}
