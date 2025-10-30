'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { createClient } from '@/lib/supabaseClient';
import { useRouter, useSearchParams } from 'next/navigation';

/**
 * Reset Password
 * - Accepts both Supabase recovery link formats:
 *   1) PKCE query param:   /reset-password?code=...
 *   2) Hash tokens:        /reset-password#type=recovery&access_token=...&refresh_token=...
 * - If no active session, we try to establish one from the URL before showing the form.
 */
function ResetPasswordInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const supabase = useMemo(() => createClient(), []);

  const [pwd, setPwd] = useState('');
  const [pwd2, setPwd2] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  // Try to ensure an authenticated session exists for the reset flow
  useEffect(() => {
    let cancelled = false;

    const parseHashParams = () => {
      const hash = typeof window !== 'undefined' ? window.location.hash : '';
      const out: Record<string, string> = {};
      if (hash && hash.startsWith('#')) {
        const pairs = hash.slice(1).split('&');
        for (const p of pairs) {
          const [k, v] = p.split('=');
          if (k) out[decodeURIComponent(k)] = decodeURIComponent(v ?? '');
        }
      }
      return out;
    };

    (async () => {
      try {
        // 1) If session already exists, we're good.
        const { data: s1 } = await supabase.auth.getSession();
        if (s1.session) {
          if (!cancelled) setChecking(false);
          return;
        }

        // 2) If we have a PKCE "code" param, exchange it.
        const code = searchParams.get('code');
        if (code) {
          const { error } = await supabase.auth.exchangeCodeForSession(code);
          if (!error) {
            if (!cancelled) setChecking(false);
            // Clean the URL (remove the code so it can't be reused)
            window.history.replaceState({}, '', '/reset-password');
            return;
          }
        }

        // 3) If we have hash tokens (access_token/refresh_token) from #type=recovery, set session.
        const hashParams = parseHashParams();
        if (hashParams['type'] === 'recovery' && hashParams['access_token'] && hashParams['refresh_token']) {
          const { error } = await supabase.auth.setSession({
            access_token: hashParams['access_token'],
            refresh_token: hashParams['refresh_token'],
          });
          if (!error) {
            if (!cancelled) setChecking(false);
            // Clean the URL (drop hash)
            window.history.replaceState({}, '', '/reset-password');
            return;
          }
        }

        // 4) Final check—if still no session, bounce to login.
        const { data: s2 } = await supabase.auth.getSession();
        if (!s2.session) {
          router.replace('/login?error=recovery_session_missing');
          return;
        }
        if (!cancelled) setChecking(false);
      } catch (e) {
        console.error('ResetPassword init error:', e);
        router.replace('/login?error=recovery_init_failed');
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);

    if (pwd.length < 8) {
      setMsg('Password must be at least 8 characters.');
      return;
    }
    if (pwd !== pwd2) {
      setMsg('Passwords do not match.');
      return;
    }

    setSaving(true);
    const { error } = await supabase.auth.updateUser({ password: pwd });
    setSaving(false);

    if (error) {
      setMsg(error.message);
      return;
    }

    setMsg('✅ Password updated. Redirecting…');
    // Optional: sign out to force fresh login with new password.
    setTimeout(async () => {
      await supabase.auth.signOut();
      router.replace('/login?pwreset=1');
    }, 1000);
  };

  if (checking) {
    return (
      <main
        style={{
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: '#0b1220',
          color: 'white',
          padding: '2rem',
        }}
      >
        <div style={{ opacity: 0.8 }}>Preparing password reset…</div>
      </main>
    );
  }

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: '#0b1220',
        color: 'white',
        padding: '2rem',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 440,
          background: 'rgba(255,255,255,0.04)',
          border: '1px solid rgba(148,163,184,0.15)',
          borderRadius: 12,
          padding: 24,
        }}
      >
        <h1 style={{ fontSize: 22, marginBottom: 16 }}>Set a new password</h1>

        {msg && (
          <div
            style={{
              marginBottom: 12,
              padding: '10px 12px',
              background: 'rgba(148,163,184,0.12)',
              borderRadius: 8,
              fontSize: 14,
            }}
          >
            {msg}
          </div>
        )}

        <form onSubmit={onSubmit}>
          <label style={{ display: 'block', fontSize: 14, marginBottom: 6 }}>New password</label>
          <input
            type="password"
            value={pwd}
            onChange={(e) => setPwd(e.target.value)}
            placeholder="••••••••"
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: 8,
              border: '1px solid rgba(148,163,184,0.25)',
              background: 'rgba(255,255,255,0.05)',
              color: 'white',
              marginBottom: 12,
            }}
          />

          <label style={{ display: 'block', fontSize: 14, marginBottom: 6 }}>Confirm password</label>
          <input
            type="password"
            value={pwd2}
            onChange={(e) => setPwd2(e.target.value)}
            placeholder="••••••••"
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: 8,
              border: '1px solid rgba(148,163,184,0.25)',
              background: 'rgba(255,255,255,0.05)',
              color: 'white',
              marginBottom: 16,
            }}
          />

          <button
            type="submit"
            disabled={saving}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: 8,
              border: '1px solid rgba(99,102,241,0.5)',
              background: saving ? 'rgba(99,102,241,0.35)' : '#1d4ed8',
              color: 'white',
              fontWeight: 600,
            }}
          >
            {saving ? 'Saving…' : 'Update password'}
          </button>
        </form>
      </div>
    </main>
  );
}

export default function ResetPassword() {
  return (
    <Suspense fallback={
      <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0b1220', color: 'white', padding: '2rem' }}>
        <div style={{ opacity: 0.8 }}>Loading…</div>
      </main>
    }>
      <ResetPasswordInner />
    </Suspense>
  );
}