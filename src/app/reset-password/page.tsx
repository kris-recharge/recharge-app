'use client';

import { useEffect, useMemo, useState } from 'react';
import { createClient } from '@/lib/supabaseClient';
import { useRouter, useSearchParams } from 'next/navigation';

/**
 * Reset Password with optional TOTP enforcement:
 * - Establishes a session from PKCE (?code=...) or hash (#type=recovery&access_token=...)
 * - If user has a verified TOTP factor, require a 6-digit code before updating password
 */
export default function ResetPassword() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const supabase = useMemo(() => createClient(), []);

  const [pwd, setPwd] = useState('');
  const [pwd2, setPwd2] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  // MFA state
  const [needsMfa, setNeedsMfa] = useState(false);
  const [mfaFactorId, setMfaFactorId] = useState<string | null>(null);
  const [mfaChallengeId, setMfaChallengeId] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState('');

  // Ensure we have a session (PKCE or hash) and detect whether TOTP is enrolled & verified
  useEffect(() => {
    let cancelled = false;

    const parseHashParams = () => {
      const hash = typeof window !== 'undefined' ? window.location.hash : '';
      const out: Record<string, string> = {};
      if (hash && hash.startsWith('#')) {
        for (const p of hash.slice(1).split('&')) {
          const [k, v] = p.split('=');
          if (k) out[decodeURIComponent(k)] = decodeURIComponent(v ?? '');
        }
      }
      return out;
    };

    (async () => {
      try {
        // 1) Already signed in?
        const { data: s1 } = await supabase.auth.getSession();
        if (!s1.session) {
          // 2) Try PKCE code
          const code = searchParams.get('code');
          if (code) {
            const { error } = await supabase.auth.exchangeCodeForSession(code);
            if (!error) {
              window.history.replaceState({}, '', '/reset-password');
            }
          } else {
            // 3) Try hash tokens from #type=recovery
            const hashParams = parseHashParams();
            if (
              hashParams['type'] === 'recovery' &&
              hashParams['access_token'] &&
              hashParams['refresh_token']
            ) {
              const { error } = await supabase.auth.setSession({
                access_token: hashParams['access_token'],
                refresh_token: hashParams['refresh_token'],
              });
              if (!error) {
                window.history.replaceState({}, '', '/reset-password');
              }
            }
          }
        }

        // 4) Final check—if still no session, bounce to login
        const { data: s2 } = await supabase.auth.getSession();
        if (!s2.session) {
          if (!cancelled) router.replace('/login?error=recovery_session_missing');
          return;
        }

        // 5) Detect verified TOTP factor
        const { data: factorsData, error: factorsErr } =
          await supabase.auth.mfa.listFactors();
        if (!factorsErr && factorsData?.totp?.length) {
          const verifiedTotp = factorsData.totp.find((f) => f.status === 'verified');
          if (verifiedTotp) {
            setNeedsMfa(true);
            setMfaFactorId(verifiedTotp.id);
          }
        }

        if (!cancelled) setChecking(false);
      } catch (e) {
        console.error('ResetPassword init error:', e);
        if (!cancelled) router.replace('/login?error=recovery_init_failed');
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Start a challenge for TOTP if needed and not already started
  const ensureMfaChallenge = async () => {
    if (!needsMfa || !mfaFactorId) return;
    if (mfaChallengeId) return;

    const { data, error } = await supabase.auth.mfa.challenge({ factorId: mfaFactorId });
    if (error) {
      setMsg(`MFA error: ${error.message}`);
      return;
    }
    setMfaChallengeId(data.id);
    setMsg('Enter the 6-digit code from your authenticator app to continue.');
  };

  const verifyMfaIfNeeded = async (): Promise<boolean> => {
    if (!needsMfa) return true; // not needed
    // Start challenge if we don't have one yet
    if (!mfaChallengeId) {
      await ensureMfaChallenge();
      return false; // show code field
    }
    if (!mfaCode || mfaCode.trim().length === 0) {
      setMsg('Please enter the 6-digit code from your authenticator app.');
      return false;
    }
    const { error } = await supabase.auth.mfa.verify({
      factorId: mfaFactorId as string,
      challengeId: mfaChallengeId,
      code: mfaCode.trim(),
    });
    if (error) {
      setMsg(`MFA verify failed: ${error.message}`);
      return false;
    }
    return true;
  };

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

    // Enforce MFA first (if applicable)
    const okToProceed = await verifyMfaIfNeeded();
    if (!okToProceed) return;

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
          {/* If TOTP is required, show the code field first */}
          {needsMfa && (
            <>
              <label style={{ display: 'block', fontSize: 14, marginBottom: 6 }}>
                6-digit authenticator code
              </label>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={6}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="••••••"
                onFocus={ensureMfaChallenge}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: '1px solid rgba(148,163,184,0.25)',
                  background: 'rgba(255,255,255,0.05)',
                  color: 'white',
                  marginBottom: 16,
                  letterSpacing: 2,
                }}
              />
            </>
          )}

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
            {saving ? 'Saving…' : needsMfa ? 'Verify & update password' : 'Update password'}
          </button>
        </form>
      </div>
    </main>
  );
}