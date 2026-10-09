"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

type Result<T> = { key: string; tick: number; data?: T; error?: unknown };

/**
 * Load data for `key` with `fetcher`; `key = null` means "not yet". Re-fetches when
 * the key changes or `reload()` is called. Keeps the previous data while reloading
 * so lists don't flash. A 401 sends the user to /login.
 */
export function useApi<T>(key: string | null, fetcher: () => Promise<T>) {
  const router = useRouter();
  const [tick, setTick] = useState(0);
  const [result, setResult] = useState<Result<T> | null>(null);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (key === null) return;
    let active = true;
    fetcherRef.current().then(
      (data) => {
        if (active) setResult({ key, tick, data });
      },
      (error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          router.replace("/login");
          return;
        }
        setResult({ key, tick, error });
      },
    );
    return () => {
      active = false;
    };
  }, [key, tick, router]);

  const sameKey = result !== null && result.key === key;
  const fresh = sameKey && result.tick === tick;
  return {
    data: sameKey ? result.data : undefined,
    error: fresh ? result.error : undefined,
    loading: key !== null && !fresh,
    reload: useCallback(() => setTick((t) => t + 1), []),
  };
}
