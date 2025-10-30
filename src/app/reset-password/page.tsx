'use client';

import { useEffect, useState } from 'react';
import { createClient } from '@/lib/supabaseClient';
import { useRouter } from 'next/navigation';

export default function ResetPassword() {
  const router = useRouter();
  const supabase = createClient();

  const [pwd, setPwd] = useState('');
  const [pwd2, setPwd2] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Require an authenticated session (recovery link should have created one)
  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) {
        router.replace('/login');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    // You can change this to /app if that’s your desired landing page
    setTimeout(() => router.replace('/login'), 1200);
  };

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