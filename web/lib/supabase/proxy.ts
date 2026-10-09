import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { userFromClaims, type SessionUser } from "@/lib/auth";

/**
 * Refresh the Supabase session cookies and read the signed-in user.
 * Returns the response to continue with; it carries any refreshed cookies.
 */
export async function updateSession(
  request: NextRequest,
): Promise<{ response: NextResponse; user: SessionUser | null }> {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet, headers) {
          for (const { name, value } of cookiesToSet) request.cookies.set(name, value);
          response = NextResponse.next({ request });
          for (const { name, value, options } of cookiesToSet) {
            response.cookies.set(name, value, options);
          }
          // e.g. Cache-Control: private, so a CDN never serves one user's cookies to another.
          for (const [key, value] of Object.entries(headers ?? {})) {
            response.headers.set(key, value);
          }
        },
      },
    },
  );

  // Do not run code between createServerClient and getClaims (Supabase guidance).
  const { data } = await supabase.auth.getClaims();
  return { response, user: userFromClaims(data?.claims) };
}

/** Redirect while keeping any cookies the session refresh just set. */
export function redirectWithCookies(request: NextRequest, from: NextResponse, path: string): NextResponse {
  const redirect = NextResponse.redirect(new URL(path, request.url));
  for (const cookie of from.cookies.getAll()) redirect.cookies.set(cookie);
  const cacheControl = from.headers.get("Cache-Control");
  if (cacheControl) redirect.headers.set("Cache-Control", cacheControl);
  return redirect;
}
