'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabaseClient';

export default function LoginPage() {
  const supabase = createClient();
  const router = useRouter();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mfaFactorId, setMfaFactorId] = useState<string | null>(null);
  const [mfaChallengeId, setMfaChallengeId] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setLoading(true);

    const { data, error } = await supabase.auth.signInWithPassword({ email, password });

    if (error) {
      setErrorMsg(error.message);
      setLoading(false);
      return;
    }

    if (data?.mfa) {
      setMfaFactorId(data.mfa.factorId);
      setMfaChallengeId(data.mfa.challengeId);
      setLoading(false);
      return;
    }

    router.replace('/app');
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
      challengeId: mfaChallengeId, // guaranteed non-null above
    });

    if (verifyRes.error) {
      setErrorMsg(verifyRes.error.message || 'Invalid code. Try again.');
      setLoading(false);
      return;
    }

    router.replace('/app');
    setLoading(false);
  }

  return (
    <main style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <form onSubmit={mfaFactorId ? onSubmitMfa : onSubmit} style={{ width: 320, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h1>Sign In</h1>

        {!mfaFactorId && (
          <>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={loading}
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
            />
          </>
        )}

        {mfaFactorId && (
          <>
            <label htmlFor="mfaCode">Enter MFA Code</label>
            <input
              id="mfaCode"
              type="text"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
              maxLength={6}
              inputMode="numeric"
              pattern="\d*"
              required
              disabled={loading}
            />
          </>
        )}

        {errorMsg && <div style={{ color: 'red' }}>{errorMsg}</div>}

        <button type="submit" disabled={loading}>
          {loading ? 'Loading…' : mfaFactorId ? 'Verify' : 'Sign In'}
        </button>
      </form>
    </main>
  );
}