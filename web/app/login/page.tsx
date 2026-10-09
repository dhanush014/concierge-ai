import type { Metadata } from "next";
import { SiteHeader } from "@/components/site-header";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="mx-auto w-full max-w-md px-6 py-12">
        <h1 className="mb-2 text-3xl font-semibold">Sign in</h1>
        <p className="mb-8 text-muted">Use the email and password for your Riverside Health account.</p>
        <LoginForm />
      </main>
    </>
  );
}
