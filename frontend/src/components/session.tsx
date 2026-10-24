"use client";

import { createContext, type ReactNode, useContext } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { Meta, User } from "@/lib/types";

interface Session {
  user: User;
  meta: Meta;
  /** UI hint only — every permission is enforced again by the API. */
  can: (permission: string) => boolean;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children, loading, error }: { children: (s: Session) => ReactNode; loading: ReactNode; error: (e: unknown, retry: () => void) => ReactNode }) {
  const me = useSWR<User>("/auth/me", fetcher, { revalidateOnFocus: false, shouldRetryOnError: false });
  const meta = useSWR<Meta>(me.data ? "/meta" : null, fetcher, { revalidateOnFocus: false });
  if (me.error) return <>{error(me.error, () => me.mutate())}</>;
  if (meta.error) return <>{error(meta.error, () => meta.mutate())}</>;
  if (!me.data || !meta.data) return <>{loading}</>;
  const session: Session = { user: me.data, meta: meta.data, can: (p) => me.data!.permissions.includes(p) };
  return <SessionContext.Provider value={session}>{children(session)}</SessionContext.Provider>;
}

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession must be used inside SessionProvider");
  return s;
}
