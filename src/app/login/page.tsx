'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { createClient } from '@/lib/supabaseClient';

type View = 'login' | 'mfa' | 'reset';

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const supabase = createClient();

  const [view, setView] = useState<View>('login');

  // login fields
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);

  // mfa fields
  const [mfaFactorId, setMfaFactorId] = useState<string | null>(null);
  const [mfaChallengeId, setMfaChallengeId] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState('');

  // reset fields
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');

  // general
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const codeFromLink = useMemo(() => searchParams?.get('code') ?? null, [searchParams]);

  // Handle links that come as URL hash from Supabase (e.g. #access_token=...&refresh_token=...&type=recovery)
  const recoveryHash = useMemo(() => {
    if (typeof window === 'undefined') return null;
    const h = window.location.hash;
    if (!h || !h.startsWith('#')) return null;
    const p = new URLSearchParams(h.slice(1));
    const access_token = p.get('access_token');
    const refresh_token = p.get('refresh_token');
    const type = p.get('type');
    if (!access_token || !refresh_token) return null;
    return { access_token, refresh_token, type } as {
      access_token: string;
      refresh_token: string;
      type: string | null;
    };
  }, [searchParams]);

  // redirect if already logged in
  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session) router.replace('/app');
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // handle password recovery/invite links that use hash tokens
  useEffect(() => {
    (async () => {
      if (!recoveryHash) return;
      // Only act on recovery or invite links
      if (recoveryHash.type && !['recovery', 'invite'].includes(recoveryHash.type)) return;
      setLoading(true);
      setErrorMsg(null);
      try {
        const { error } = await supabase.auth.setSession({
          access_token: recoveryHash.access_token,
          refresh_token: recoveryHash.refresh_token,
        });
        if (error) {
          setErrorMsg(error.message || 'Could not start password reset.');
        } else {
          // Clean the hash from the URL so refreshes don't repeat it
          const url = new URL(window.location.href);
          url.hash = '';
          window.history.replaceState({}, '', url.toString());
          setView('reset');
        }
      } catch (e: any) {
        setErrorMsg(e?.message ?? 'Could not start password reset.');
      } finally {
        setLoading(false);
      }
    })();
  }, [recoveryHash, supabase]);

  // handle password recovery link (?code=...)
  useEffect(() => {
    (async () => {
      if (!codeFromLink) return;
      setLoading(true);
      setErrorMsg(null);
      try {
        const { error } = await supabase.auth.exchangeCodeForSession(codeFromLink);
        if (error) {
          setErrorMsg(error.message || 'Could not start password reset.');
        } else {
          setView('reset');
        }
      } catch (e: any) {
        setErrorMsg(e?.message ?? 'Could not start password reset.');
      } finally {
        setLoading(false);
      }
    })();
  }, [codeFromLink, supabase]);

  async function onSubmitLogin(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setLoading(true);

    const { data, error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });

    if (error) {
      setErrorMsg(error.message);
      setLoading(false);
      return;
    }

    if (data.session) {
      router.replace('/app');
      setLoading(false);
      return;
    }

    const factorsRes = await supabase.auth.mfa.listFactors();
    if (factorsRes.error) {
      setErrorMsg(factorsRes.error.message || 'Unable to load MFA factors.');
      setLoading(false);
      return;
    }

    const totp = factorsRes.data.totp?.[0];
    if (!totp?.id) {
      setErrorMsg('MFA is required but no TOTP factor is enrolled for this account.');
      setLoading(false);
      return;
    }

    const challengeRes = await supabase.auth.mfa.challenge({ factorId: totp.id });
    if (challengeRes.error) {
      setErrorMsg(challengeRes.error.message || 'Could not start MFA challenge.');
      setLoading(false);
      return;
    }

    setMfaFactorId(totp.id);
    setMfaChallengeId(challengeRes.data?.id ?? null);
    setView('mfa');
    setLoading(false);
  }

  async function onSubmitMfa(e: React.FormEvent) {
    e.preventDefault();
    if (!mfaFactorId) {
      setErrorMsg('Missing MFA factor.');
      return;
    }
    if (!mfaChallengeId) {
      setErrorMsg('MFA challenge missing or expired. Please sign in again to start a new challenge.');
      return;
    }

    setErrorMsg(null);
    setLoading(true);

    const verifyRes = await supabase.auth.mfa.verify({
      factorId: mfaFactorId,
      code: mfaCode.trim(),
      challengeId: mfaChallengeId, // required and guaranteed non-null above
    });

    if (verifyRes.error) {
      setErrorMsg(verifyRes.error.message || 'Invalid code. Try again.');
      setLoading(false);
      return;
    }

    router.replace('/app');
    setLoading(false);
  }

  async function handleForgotPassword(e: React.MouseEvent<HTMLAnchorElement>) {
    e.preventDefault();
    if (!email) {
      setErrorMsg('Enter your email above, then click “Forgot Password?”');
      return;
    }
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/login`,
      });
      if (error) setErrorMsg(error.message);
      else setErrorMsg('Password reset email sent. Check your inbox.');
    } catch (err: any) {
      setErrorMsg(err?.message ?? 'Could not start password reset.');
    }
  }

  async function handleReset(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);

    if (newPw.length < 8) {
      setErrorMsg('Password must be at least 8 characters.');
      return;
    }
    if (newPw !== confirmPw) {
      setErrorMsg('Passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: newPw });
      if (error) {
        setErrorMsg(error.message);
      } else {
        const url = new URL(window.location.href);
        url.searchParams.delete('code');
        url.hash = '';
        window.history.replaceState({}, '', url.toString());
        setNewPw('');
        setConfirmPw('');
        setErrorMsg('Password updated. Redirecting…');
        // Recovery/invite flows yield a valid session; go straight to the app.
        setTimeout(() => router.replace('/app'), 600);
      }
    } catch (err: any) {
      setErrorMsg(err?.message ?? 'Could not update password.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#eef1f5',
        padding: 24,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 420,
          background: '#ffffff',
          borderRadius: 12,
          boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)',
          padding: 24,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
          <img
            src="/ReChargeLogo_REVA.png"
            alt="ReCharge Alaska"
            width={140}
            height={140}
            style={{ objectFit: 'contain' }}
          />
        </div>

        {view === 'login' && (
          <h1 style={{ fontSize: 20, fontWeight: 600, textAlign: 'center', marginBottom: 12, color: '#0b1830' }}>
            Sign in
          </h1>
        )}
        {view === 'mfa' && (
          <h1 style={{ fontSize: 20, fontWeight: 600, textAlign: 'center', marginBottom: 12, color: '#0b1830' }}>
            Enter 6-digit code
          </h1>
        )}
        {view === 'reset' && (
          <h1 style={{ fontSize: 20, fontWeight: 600, textAlign: 'center', marginBottom: 12, color: '#0b1830' }}>
            Reset your password
          </h1>
        )}

        {errorMsg && (
          <div
            role="alert"
            style={{
              background: '#fef2f2',
              color: '#991b1b',
              border: '1px solid #fecaca',
              borderRadius: 8,
              padding: '10px 12px',
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            {errorMsg}
          </div>
        )}

        {view === 'login' && (
          <form onSubmit={onSubmitLogin}>
            <label htmlFor="email" style={{ display: 'block', fontSize: 14, color: '#334155', marginBottom: 6 }}>
              Email address
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              style={{
                width: '100%',
                border: '1px solid #cbd5e1',
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 14,
                marginBottom: 14,
                outline: 'none',
              }}
            />

            <label htmlFor="password" style={{ display: 'block', fontSize: 14, color: '#334155', marginBottom: 6 }}>
              Password
            </label>
            <div style={{ position: 'relative', marginBottom: 10 }}>
              <input
                id="password"
                type={showPw ? 'text' : 'password'}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  width: '100%',
                  border: '1px solid #cbd5e1',
                  borderRadius: 8,
                  padding: '10px 40px 10px 12px',
                  fontSize: 14,
                  outline: 'none',
                }}
              />
              <button
                type="button"
                onClick={() => setShowPw((s) => !s)}
                aria-label={showPw ? 'Hide password' : 'Show password'}
                style={{
                  position: 'absolute',
                  right: 8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  color: '#475569',
                }}
              >
                {showPw ? '🙈' : '👁️'}
              </button>
            </div>

            <div style={{ textAlign: 'right', marginBottom: 14 }}>
              <a href="#" onClick={handleForgotPassword} style={{ fontSize: 13, color: '#2563eb', textDecoration: 'none' }}>
                Forgot Password?
              </a>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%',
                background: '#1f3a8a',
                color: 'white',
                border: 'none',
                borderRadius: 10,
                padding: '12px 14px',
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        )}

        {view === 'mfa' && (
          <form onSubmit={onSubmitMfa}>
            <label htmlFor="mfa" style={{ display: 'block', fontSize: 14, color: '#334155', marginBottom: 6 }}>
              6-digit code
            </label>
            <input
              id="mfa"
              type="text"
              inputMode="numeric"
              pattern="\\d*"
              maxLength={6}
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value)}
              style={{
                width: '100%',
                border: '1px solid #cbd5e1',
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 14,
                marginBottom: 14,
                outline: 'none',
                letterSpacing: 3,
                textAlign: 'center',
              }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                onClick={() => {
                  setView('login');
                  setMfaCode('');
                  setErrorMsg(null);
                }}
                style={{
                  flex: 1,
                  background: '#e2e8f0',
                  color: '#0f172a',
                  border: 'none',
                  borderRadius: 10,
                  padding: '12px 14px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Back
              </button>
              <button
                type="submit"
                disabled={loading || mfaCode.length !== 6}
                style={{
                  flex: 1,
                  background: '#1f3a8a',
                  color: 'white',
                  border: 'none',
                  borderRadius: 10,
                  padding: '12px 14px',
                  fontWeight: 600,
                  cursor: loading ? 'not-allowed' : 'pointer',
                }}
              >
                {loading ? 'Verifying…' : 'Verify'}
              </button>
            </div>
          </form>
        )}

        {view === 'reset' && (
          <form onSubmit={handleReset}>
            <label htmlFor="newpw" style={{ display: 'block', fontSize: 14, color: '#334155', marginBottom: 6 }}>
              New password
            </label>
            <input
              id="newpw"
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              minLength={8}
              required
              style={{
                width: '100%',
                border: '1px solid #cbd5e1',
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 14,
                marginBottom: 14,
                outline: 'none',
              }}
            />

            <label htmlFor="confirmpw" style={{ display: 'block', fontSize: 14, color: '#334155', marginBottom: 6 }}>
              Confirm new password
            </label>
            <input
              id="confirmpw"
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              minLength={8}
              required
              style={{
                width: '100%',
                border: '1px solid #cbd5e1',
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 14,
                marginBottom: 14,
                outline: 'none',
              }}
            />

            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                onClick={() => setView('login')}
                style={{
                  flex: 1,
                  background: '#e2e8f0',
                  color: '#0f172a',
                  border: 'none',
                  borderRadius: 10,
                  padding: '12px 14px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={loading}
                style={{
                  flex: 1,
                  background: '#1f3a8a',
                  color: 'white',
                  border: 'none',
                  borderRadius: 10,
                  padding: '12px 14px',
                  fontWeight: 600,
                  cursor: loading ? 'not-allowed' : 'pointer',
                }}
              >
                {loading ? 'Updating…' : 'Update password'}
              </button>
            </div>
          </form>
        )}
      </div>
    </main>
  );
}