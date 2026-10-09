import { redirect } from "next/navigation";
import { Suspense } from "react";
import { getUser, homeFor } from "@/lib/auth";

// proxy.ts normally redirects "/" before this renders. This is the fallback.
export default function Home() {
  return (
    <Suspense>
      <GoHome />
    </Suspense>
  );
}

async function GoHome(): Promise<null> {
  const user = await getUser();
  redirect(user ? homeFor(user.role) : "/login");
}
