import { Suspense } from "react";
import { AccountBar } from "@/components/account-bar";
import { RoleGate } from "@/components/role-gate";
import { SiteHeader } from "@/components/site-header";
import { PortalTabs, TabList } from "./portal-tabs";

export default function PortalLayout({ children }: LayoutProps<"/portal">) {
  return (
    <>
      <SiteHeader>
        <Suspense fallback={null}>
          <AccountBar role="patient" />
        </Suspense>
      </SiteHeader>
      <Suspense fallback={<TabList pathname={null} />}>
        <PortalTabs />
      </Suspense>
      <main id="main" className="mx-auto w-full max-w-4xl px-6 py-10">
        <Suspense fallback={<p className="text-muted">Loading…</p>}>
          <RoleGate role="patient">{children}</RoleGate>
        </Suspense>
      </main>
    </>
  );
}
