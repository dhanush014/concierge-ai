import { purgeE2EDoctors, purgeE2EDocuments } from "./helpers";

/** Start of every run: remove test data left behind by a run that crashed. */
export default async function globalSetup(): Promise<void> {
  const removed = await purgeE2EDoctors();
  if (removed > 0) console.log(`Removed ${removed} leftover E2E doctor(s).`);
  const docs = await purgeE2EDocuments();
  if (docs > 0) console.log(`Removed ${docs} leftover E2E document(s).`);
}
