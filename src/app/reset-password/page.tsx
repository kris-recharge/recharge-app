'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { createClient } from '@/lib/supabaseClient';
import { useRouter, useSearchParams } from 'next/navigation';

/**
 * Reset Password with optional TOTP verification
 * - Accepts both recovery URL formats (PKCE ?code= and hash #access_token=...)
 * - If the user has a verified TOTP factor, require a 6-digit code before updating.
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

  // MFA state
  const [hasTotp, setHasTotp] = useState(false);
  const [factorId, setFactorId] = useState<string | null>(null);
  const [otp, setOtp] = useState('');
  const [challengeId, setChallengeId] = useState<string | null>(null);

  // Try to ensure an authenticated session exists for the reset flow,
  // then discover if the user has a verified TOTP factor.
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
        // 1) If session already exists, continue
        let { data: s1 } = await supabase.auth.getSession();
        if (!s1.session) {
          // 2) Try PKCE exchange
          const code = searchParams.get('code');
          if (code) {
            await supabase.auth.exchangeCodeForSession(code);
            ({ data: s1 } = await supabase.auth.getSession());
          }
        }
        if (!s1.session) {
          // 3) Try hash tokens (type=recovery)
          const hashParams = parseHashParams();
          if (hashParams['type'] === 'recovery' && hashParams['access_token'] && hashParams['refresh_token']) {
            await supabase.auth.setSession({
              access_token: hashParams['access_token'],
              refresh_token: hashParams['refresh_token'],
            });
            window.history.replaceState({}, '', '/reset-password');
          }
        }

        // 4) Final check
        const { data: s2 } = await supabase.auth.getSession();
        if (!s2.session) {
          router.replace('/login?error=recovery_session_missing');
          return;
        }

        // 5) Discover verified TOTP factor
        const { data: factors, error } = await supabase.auth.mfa.listFactors();
        if (!error && factors?.all?.length) {
          const totp = factors.all.find(
            (f) => f.factor_type === 'totp' && f.status === 'verified'
          );
          if (totp) {
            setHasTotp(true);
            setFactorId(totp.id);
          }
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

  const requireStrongPwd = () => pwd.length >= 8;

  const ensureMfaVerified = async () => {
    if (!hasTotp) return true;                // no TOTP enrolled
    if (!factorId) return false;

    // Require user to enter the code
    if (!otp || otp.trim().length < 6) {
      setMsg('Enter the 6-digit code from your authenticator.');
      return false;
    }

    // Start challenge if we don't have one
    let cid = challengeId;
    if (!cid) {
      const { data, error } = await supabase.auth.mfa.challenge({ factorId });
      if (error) {
        setMsg(error.message);
        return false;
      }
      cid = data?.id ?? null;
      setChallengeId(cid);
      if (!cid) {
        setMsg('Unable to start MFA challenge.');
        return false;
      }
    }

    // Verify code
    const verify = await supabase.auth.mfa.verify({
      factorId,
      challengeId: cid,
      code: otp.trim(),
    });
    if (verify.error) {
      setMsg(verify.error.message || 'Invalid authentication code.');
      return false;
    }
    return true;
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);

    if (!requireStrongPwd()) {
      setMsg('Password must be at least 8 characters.');
      return;
    }
    if (pwd !== pwd2) {
      setMsg('Passwords do not match.');
      return;
    }

    // If TOTP is enrolled, enforce verification first
    const ok = await ensureMfaVerified();
    if (!ok) return;

    setSaving(true);
    const { error } = await supabase.auth.updateUser({ password: pwd });
    setSaving(false);

    if (error) {
      setMsg(error.message);
      return;
    }

    setMsg('✅ Password updated. Redirecting…');
    setTimeout(async () => {
      await supabase.auth.signOut();
      router.replace('/login?pwreset=1');
    }, 900);
  };

  if (checking) {
    return (
      <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0b1220', color: 'white', padding: '2rem' }}>
        <div style={{ opacity: 0.8 }}>Preparing password reset…</div>
      </main>
    );
  }

  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0b1220', color: 'white', padding: '2rem' }}>
      <div style={{ width: '100%', maxWidth: 440, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.15)', borderRadius: 12, padding: 24 }}>
        <h1 style={{ fontSize: 22, marginBottom: 16 }}>Set a new password</h1>

        {msg && (
          <div style={{ marginBottom: 12, padding: '10px 12px', background: 'rgba(148,163,184,0.12)', borderRadius: 8, fontSize: 14 }}>
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
            autoComplete="new-password"
            style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.25)', background: 'rgba(255,255,255,0.05)', color: 'white', marginBottom: 12 }}
          />

          <label style={{ display: 'block', fontSize: 14, marginBottom: 6 }}>Confirm password</label>
          <input
            type="password"
            value={pwd2}
            onChange={(e) => setPwd2(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.25)', background: 'rgba(255,255,255,0.05)', color: 'white', marginBottom: hasTotp ? 12 : 16 }}
          />

          {hasTotp && (
            <>
              <label style={{ display: 'block', fontSize: 14, marginBottom: 6 }}>Authenticator code</label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D+/g, '').slice(0, 6))}
                placeholder="6-digit code"
                autoComplete="one-time-code"
                style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.25)', background: 'rgba(255,255,255,0.05)', color: 'white', marginBottom: 16, letterSpacing: 2 }}
              />
            </>
          )}

          <button
            type="submit"
            disabled={saving}
            style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid rgba(99,102,241,0.5)', background: saving ? 'rgba(99,102,241,0.35)' : '#1d4ed8', color: 'white', fontWeight: 600 }}
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
        <div style={{ opacity: 0.8 }}>Preparing password reset…</div>
      </main>
    }>
      <ResetPasswordInner />
    </Suspense>
  );
}