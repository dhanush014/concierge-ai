import type { Metadata } from "next";
import { Suspense } from "react";
import { BookFlow } from "./book-flow";

export const metadata: Metadata = { title: "Book a visit" };

export default function BookPage() {
  return (
    <Suspense fallback={<p className="text-muted">Loading…</p>}>
      <BookFlow />
    </Suspense>
  );
}
