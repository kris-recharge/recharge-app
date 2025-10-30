'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { createClient } from '@/lib/supabaseClient';

export default function AuthCallback() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [msg, setMsg] = useState('Finishing sign-in…');

  useEffect(() => {
    const supabase = createClient();

    (async () => {
      try {
        // --- Case A: PKCE code flow ?code=... ---
        const code = searchParams.get('code');
        if (code) {
          // This exchanges the auth code (and the stored code_verifier cookie) for a session
          const { error } = await supabase.auth.exchangeCodeForSession(code);
          if (error) throw error;

          router.replace('/reset-password');
          return;
        }

        // --- Case B: Hash-based recovery flow #access_token=...&refresh_token=...&type=recovery ---
        if (typeof window !== 'undefined' && window.location.hash.startsWith('#')) {
          const hash = new URLSearchParams(window.location.hash.substring(1));
          const type = hash.get('type');
          const access_token = hash.get('access_token');
          const refresh_token = hash.get('refresh_token');

          if (type === 'recovery' && access_token && refresh_token) {
            const { error } = await supabase.auth.setSession({ access_token, refresh_token });
            if (error) throw error;

            router.replace('/reset-password');
            return;
          }
        }

        // Nothing we can process: send back to login
        router.replace('/login');
      } catch (err: any) {
        console.error(err);
        setMsg(err?.message || 'Something went wrong. Redirecting…');
        setTimeout(() => router.replace('/login'), 1500);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        color: '#94a3b8',
      }}
    >
      {msg}
    </main>
  );
}