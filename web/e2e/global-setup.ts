import { purgeE2EDoctors } from "./helpers";

/** Start of every run: remove test doctors left behind by a run that crashed. */
export default async function globalSetup(): Promise<void> {
  const removed = await purgeE2EDoctors();
  if (removed > 0) console.log(`Removed ${removed} leftover E2E doctor(s).`);
}
