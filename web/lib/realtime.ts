import { createClient } from "@/lib/supabase/browser";

type Watch = { table: "messages" | "conversations" | "handoffs"; filter?: string };

/**
 * Call `onChange` when a watched row is inserted or updated (Supabase Realtime, limited
 * by the database's read policies). Realtime is only a "something changed" signal:
 * callers reload from the API, which stays the one source of truth. Also fires once
 * when the subscription is up, to catch anything that changed while connecting.
 * Returns an unsubscribe function.
 */
export function watchTables(name: string, watches: Watch[], onChange: () => void): () => void {
  const supabase = createClient();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const fire = () => {
    clearTimeout(timer);
    timer = setTimeout(onChange, 150); // several rows from one action -> one reload
  };

  const channel = supabase.channel(`${name}-${Math.random().toString(36).slice(2)}`);
  for (const w of watches) {
    channel.on("postgres_changes", { event: "*", schema: "public", table: w.table, filter: w.filter }, fire);
  }

  let cancelled = false;
  void supabase.auth.getSession().then(async ({ data }) => {
    if (cancelled) return;
    await supabase.realtime.setAuth(data.session?.access_token ?? null);
    channel.subscribe((status) => {
      if (status === "SUBSCRIBED") fire();
    });
  });

  return () => {
    cancelled = true;
    clearTimeout(timer);
    void supabase.removeChannel(channel);
  };
}
