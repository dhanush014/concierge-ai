import { redirect } from "next/navigation";
import { connection } from "next/server";
import { cache } from "react";
import { createClient } from "@/lib/supabase/server";

export type Role = "patient" | "staff";

export type SessionUser = {
  role: Role;
  displayName: string;
};

/**
 * Narrow user from verified token claims. `user_role` is added to every token by
 * the custom access token hook (supabase/migrations/0003_role_claim.sql).
 * Returns null when there is no session or the account has no role.
 */
export function userFromClaims(claims: Record<string, unknown> | null | undefined): SessionUser | null {
  if (!claims) return null;
  const role = claims.user_role;
  if (role !== "patient" && role !== "staff") return null;

  const meta = claims.user_metadata;
  const name =
    typeof meta === "object" && meta !== null && "display_name" in meta
      ? String(meta.display_name)
      : "";
  return { role, displayName: name };
}

export function homeFor(role: Role): string {
  return role === "staff" ? "/staff" : "/portal";
}

/**
 * The signed-in user, verified with getClaims() (checks the token signature).
 * cache(): read once per request even if several components ask.
 * connection(): always run at request time. Token checks compare against the
 * current time, which Cache Components won't allow during prerendering.
 */
export const getUser = cache(async (): Promise<SessionUser | null> => {
  await connection();
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  return userFromClaims(data?.claims);
});

/** Redirects away unless the signed-in user has `role`. */
export async function requireRole(role: Role): Promise<SessionUser> {
  const user = await getUser();
  if (!user) redirect("/login");
  if (user.role !== role) redirect(homeFor(user.role));
  return user;
}
