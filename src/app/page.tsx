'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function RootRedirect() {
  const router = useRouter();

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const { hash } = window.location;
      if (hash && hash.startsWith('#')) {
        // Preserve Supabase tokens and recovery links when redirecting
        window.location.replace(`/login${hash}`);
        return;
      }
    }
    // Default redirect if no hash present
    router.replace('/login');
  }, [router]);

  return (
    <main style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>
      Redirecting to login…
    </main>
  );
}