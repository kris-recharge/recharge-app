'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/**
 * Root route
 * - Hard-redirects to /login while preserving any Supabase recovery tokens
 *   or query params (?code=..., etc.).
 * - Uses window.location.replace for hash-bearing links because hashes are
 *   not available to the server and need a full client redirect to keep them.
 * - Falls back to router.replace('/login') when there is no hash or query.
 */
export default function RootRedirect() {
  const router = useRouter();

  useEffect(() => {
    // Only run in the browser
    if (typeof window === 'undefined') return;

    const { hash, search } = window.location;

    // If we have recovery/access tokens in the hash OR query params,
    // forward the user to /login and preserve both.
    const hasHash = !!hash && hash.startsWith('#');
    const hasQuery = !!search && search.length > 1;

    if (hasHash || hasQuery) {
      const next = `/login${hasQuery ? search : ''}${hasHash ? hash : ''}`;
      // Hard navigation so tokens in the URL hash are preserved verbatim
      window.location.replace(next);
      return;
    }

    // Default: soft redirect to /login
    router.replace('/login');
  }, [router]);

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#94a3b8',
      }}
    >
      Redirecting to login…
    </main>
  );
}