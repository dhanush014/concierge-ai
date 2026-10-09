import type { NextRequest } from "next/server";
import { homeFor } from "@/lib/auth";
import { redirectWithCookies, updateSession } from "@/lib/supabase/proxy";

/**
 * Runs before every page. Refreshes the session, then does fast role-based redirects.
 * These are convenience checks only: each protected layout checks again on the server,
 * and the FastAPI backend verifies the token on every call.
 */
export async function proxy(request: NextRequest) {
  const { response, user } = await updateSession(request);
  const path = request.nextUrl.pathname;
  const go = (to: string) => redirectWithCookies(request, response, to);

  if (!user) {
    return path === "/login" ? response : go("/login");
  }

  const home = homeFor(user.role);
  if (path === "/" || path === "/login") return go(home);
  if (path.startsWith("/staff") && user.role !== "staff") return go(home);
  if (path.startsWith("/portal") && user.role !== "patient") return go(home);
  return response;
}

export const config = {
  matcher: [
    // Everything except Next internals and static files.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
