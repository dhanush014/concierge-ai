"use client";

import { useActionState } from "react";
import { signIn, type SignInState } from "@/app/auth-actions";

const initialState: SignInState = { error: null };

const inputClass =
  "w-full rounded-md border border-line px-4 py-3 text-lg text-ink aria-[invalid=true]:border-danger";

export function LoginForm() {
  const [state, formAction, pending] = useActionState(signIn, initialState);
  const hasError = state.error !== null;

  return (
    <form action={formAction} className="flex flex-col gap-6" noValidate>
      <div className="flex flex-col gap-2">
        <label htmlFor="email" className="font-medium">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          aria-invalid={hasError}
          aria-describedby={hasError ? "login-error" : undefined}
          className={inputClass}
        />
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="password" className="font-medium">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={hasError}
          aria-describedby={hasError ? "login-error" : undefined}
          className={inputClass}
        />
      </div>

      {/* Always in the DOM so screen readers announce changes. */}
      <p id="login-error" role="alert" className="min-h-[1.6em] font-medium text-danger">
        {state.error}
      </p>

      <button
        type="submit"
        disabled={pending}
        className="rounded-md bg-accent px-6 py-3 text-lg font-semibold text-white hover:bg-accent-hover disabled:opacity-70"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
