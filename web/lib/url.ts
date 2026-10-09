/** `path?k=v&...`, skipping null/undefined/empty values. */
export function hrefWith(path: string, values: Record<string, string | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value) query.set(key, value);
  }
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}
