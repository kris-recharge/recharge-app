'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabaseClient';

export default function LoginPage() {
  const router = useRouter();
  const supabase = createClient();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // redirect if already logged in
  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session) router.replace('/app');
    })();
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setLoading(true);

    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });

    if (error) setErrorMsg(error.message);
    else router.replace('/app');

    setLoading(false);
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
          boxShadow:
            '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)',
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

        <h1
          style={{
            fontSize: 20,
            fontWeight: 600,
            textAlign: 'center',
            marginBottom: 12,
            color: '#0b1830',
          }}
        >
          Sign in
        </h1>

        <form onSubmit={onSubmit}>
          <label
            htmlFor="email"
            style={{ display: 'block', fontSize: 14, color: '#334155', marginBottom: 6 }}
          >
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

          <label
            htmlFor="password"
            style={{ display: 'block', fontSize: 14, color: '#334155', marginBottom: 6 }}
          >
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
            <a
              href="#"
              onClick={async (e) => {
                e.preventDefault();
                if (!email) {
                  setErrorMsg('Enter your email above, then click “Forgot Password?”');
                  return;
                }
                try {
                  const { error } = await supabase.auth.resetPasswordForEmail(email, {
                    redirectTo: `${window.location.origin}/login`,
                  });
                  if (error) setErrorMsg(error.message);
                  else setErrorMsg('Password reset email sent. Check your inbox.');
                } catch (err: any) {
                  setErrorMsg(err?.message ?? 'Could not start password reset.');
                }
              }}
              style={{ fontSize: 13, color: '#2563eb', textDecoration: 'none' }}
            >
              Forgot Password?
            </a>
          </div>

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
      </div>
    </main>
  );
}