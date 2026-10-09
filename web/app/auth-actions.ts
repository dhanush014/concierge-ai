"use server";

import { redirect } from "next/navigation";
import { homeFor, userFromClaims } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

export type SignInState = { error: string | null };

export async function signIn(_prev: SignInState, formData: FormData): Promise<SignInState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  if (!email || !password) {
    return { error: "Enter your email and password." };
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    // Same message for unknown email and wrong password.
    return { error: "Email or password is incorrect." };
  }

  const { data } = await supabase.auth.getClaims();
  const user = userFromClaims(data?.claims);
  if (!user) {
    await supabase.auth.signOut();
    return { error: "This account doesn't have access to the portal. Please call us." };
  }
  redirect(homeFor(user.role));
}

export async function signOut(): Promise<void> {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}
