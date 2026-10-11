import type { Metadata } from "next";
import { InboxView } from "./inbox-view";

export const metadata: Metadata = { title: "Staff inbox" };

export default function StaffPage() {
  return <InboxView />;
}
