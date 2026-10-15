"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// Re-renders the screen from the server every few seconds, so a waiting
// senior sees their helper arrive and both sides see new messages.
// ponytail: polling, not a socket. Supabase Realtime replaces this when the
// store moves there.
export default function Poll({ every = 4000 }: { every?: number }) {
  const router = useRouter();
  useEffect(() => {
    const t = setInterval(() => router.refresh(), every);
    return () => clearInterval(t);
  }, [router, every]);
  return null;
}
