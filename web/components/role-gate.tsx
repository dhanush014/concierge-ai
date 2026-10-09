import type { ReactNode } from "react";
import { requireRole, type Role } from "@/lib/auth";

/**
 * Server-side check that the signed-in user has `role`, else redirect.
 * proxy.ts already redirects; this is the check that doesn't rely on it.
 * Reads the session, so render inside <Suspense>.
 */
export async function RoleGate({ role, children }: { role: Role; children: ReactNode }) {
  await requireRole(role);
  return <>{children}</>;
}
