import { signOut } from "@/app/auth-actions";
import { requireRole, type Role } from "@/lib/auth";

/** "Signed in as …" plus a Sign out button. Reads the session, so render inside <Suspense>. */
export async function AccountBar({ role }: { role: Role }) {
  const user = await requireRole(role);
  return (
    <div className="flex items-center gap-4">
      <p className="text-muted">
        Signed in as <span className="font-medium text-ink">{user.displayName || "you"}</span>
      </p>
      <form action={signOut}>
        <button
          type="submit"
          className="rounded-md border border-accent px-4 py-2 font-medium text-accent hover:bg-accent-soft"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
