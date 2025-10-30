'use client';
import { useEffect, useMemo, useState } from 'react';
import { createClient } from '@/lib/supabaseClient';

// Account Security: Enroll, verify, and disable TOTP (no server refs)
export default function SecurityPage() {
  const supabase = useMemo(() => createClient(), []);

  // TOTP state
  const [enrolled, setEnrolled] = useState(false);
  const [factorId, setFactorId] = useState<string | null>(null);
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpUri, setOtpUri] = useState<string | null>(null);
  const [code, setCode] = useState('');

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [dangerMode, setDangerMode] = useState<'none' | 'remove'>('none');

  // Load current factor status
  useEffect(() => {
    (async () => {
      setMsg(null);
      const { data, error } = await supabase.auth.mfa.listFactors();
      if (error) {
        setMsg(error.message);
        return;
      }
      const verified = data?.totp?.find((f) => f.status === 'verified');
      if (verified) {
        setEnrolled(true);
        setFactorId(verified.id);
      } else {
        setEnrolled(false);
        setFactorId(null);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Enroll flow ----
  async function startEnroll() {
    setMsg(null);
    setBusy(true);
    setCode('');
    try {
      // 1) Enroll TOTP factor
      const { data: enrollData, error: enrollErr } = await supabase.auth.mfa.enroll({ factorType: 'totp' });
      if (enrollErr) throw enrollErr;
      setFactorId(enrollData.id);
      setOtpUri(enrollData.totp?.uri ?? null);

      // 2) Create a challenge
      const { data: challengeData, error: challengeErr } = await supabase.auth.mfa.challenge({ factorId: enrollData.id });
      if (challengeErr) throw challengeErr;
      setChallengeId(challengeData.id);

      setMsg('Scan the QR code with your authenticator app, then enter the 6‑digit code.');
    } catch (e: any) {
      setMsg(e?.message ?? 'Could not start TOTP enrollment.');
      setOtpUri(null);
      setFactorId(null);
    } finally {
      setBusy(false);
    }
  }

  async function verifyEnroll() {
    if (!factorId || !challengeId) {
      setMsg('Missing challenge. Click “Set up Authenticator” again.');
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const { error } = await supabase.auth.mfa.verify({ factorId, challengeId, code: code.trim() });
      if (error) throw error;
      setMsg('✅ Authenticator added.');
      setEnrolled(true);
      setOtpUri(null);
      setChallengeId(null);
      setCode('');
    } catch (e: any) {
      setMsg(e?.message ?? 'Verification failed.');
    } finally {
      setBusy(false);
    }
  }

  // ---- Remove flow ----
  async function beginDisable() {
    if (!factorId) {
      setMsg('No TOTP factor to remove.');
      return;
    }
    setBusy(true);
    setMsg(null);
    setCode('');
    try {
      const { data, error } = await supabase.auth.mfa.challenge({ factorId });
      if (error) throw error;
      setChallengeId(data.id);
      setDangerMode('remove');
      setMsg('Confirm removal by entering a 6‑digit code from your authenticator app.');
    } catch (e: any) {
      setMsg(e?.message ?? 'Could not start removal challenge.');
    } finally {
      setBusy(false);
    }
  }

  async function confirmDisable() {
    if (!factorId || !challengeId) return;
    setBusy(true);
    setMsg(null);
    try {
      // Verify a fresh TOTP code for removal action
      const { error: vErr } = await supabase.auth.mfa.verify({ factorId, challengeId, code: code.trim() });
      if (vErr) throw vErr;

      const { error: uErr } = await supabase.auth.mfa.unenroll({ factorId });
      if (uErr) throw uErr;

      setMsg('✅ Authenticator disabled.');
      setEnrolled(false);
      setFactorId(null);
      setChallengeId(null);
      setCode('');
      setDangerMode('none');
    } catch (e: any) {
      setMsg(e?.message ?? 'Failed to disable authenticator.');
    } finally {
      setBusy(false);
    }
  }

  function DangerRemovePanel() {
    if (dangerMode !== 'remove') return null;
    return (
      <div style={{ marginTop: 12 }}>
        <label style={{ display: 'block', fontSize: 14, marginBottom: 6 }}>6‑digit code</label>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          placeholder="123456"
          inputMode="numeric"
          maxLength={6}
          pattern="\\d*"
          style={{ width: '100%', border: '1px solid #cbd5e1', borderRadius: 8, padding: '10px 12px' }}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button
            onClick={confirmDisable}
            disabled={busy || code.length !== 6}
            style={{ flex: 1, background: '#b91c1c', color: '#fff', border: 'none', borderRadius: 10, padding: '12px 14px', fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer' }}
          >
            {busy ? 'Removing…' : 'Confirm disable'}
          </button>
          <button
            onClick={() => { setDangerMode('none'); setChallengeId(null); setCode(''); setMsg(null); }}
            disabled={busy}
            style={{ flex: 1, background: '#e5e7eb', color: '#111827', border: 'none', borderRadius: 10, padding: '12px 14px', fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer' }}
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <main style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: '#eef1f5' }}>
      <div style={{ background: '#fff', padding: 24, borderRadius: 12, width: '100%', maxWidth: 560, boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)' }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8, color: '#0b1830' }}>Account security</h1>
        <p style={{ marginBottom: 16, color: '#334155' }}>Manage your authenticator (TOTP) for this account.</p>

        {msg && (
          <div style={{ marginBottom: 12, color: msg.startsWith('✅') ? '#166534' : '#991b1b' }}>{msg}</div>
        )}

        {/* ENROLLED VIEW */}
        {enrolled && !otpUri && dangerMode === 'none' && (
          <>
            <div style={{ marginBottom: 12 }}>✅ TOTP is enabled for this account.</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={beginDisable}
                disabled={busy}
                style={{ flex: 1, background: '#dc2626', color: '#fff', border: 'none', borderRadius: 10, padding: '12px 14px', fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer' }}
              >
                {busy ? 'Working…' : 'Disable authenticator'}
              </button>
              <button
                onClick={startEnroll}
                disabled={busy}
                title="Re-enroll (will create a new QR and require verification again)"
                style={{ flex: 1, background: '#1f3a8a', color: '#fff', border: 'none', borderRadius: 10, padding: '12px 14px', fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer' }}
              >
                {busy ? 'Starting…' : 'Reset / re-enroll'}
              </button>
            </div>
          </>
        )}

        {/* DANGER (REMOVE) PANEL */}
        {dangerMode === 'remove' && <DangerRemovePanel />}

        {/* ENROLL FLOW (QR + VERIFY) */}
        {!enrolled && otpUri && (
          <>
            <p style={{ margin: '12px 0' }}>Scan this QR in Google Authenticator / 1Password / Authy:</p>
            <img
              src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(otpUri)}`}
              alt="TOTP QR"
              width={180}
              height={180}
              style={{ border: '1px solid #e2e8f0', borderRadius: 8 }}
            />
            <div style={{ marginTop: 12 }}>
              <label style={{ display: 'block', fontSize: 14, marginBottom: 6 }}>6‑digit code</label>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                placeholder="123456"
                inputMode="numeric"
                maxLength={6}
                pattern="\\d*"
                style={{ width: '100%', border: '1px solid #cbd5e1', borderRadius: 8, padding: '10px 12px' }}
              />
              <button
                onClick={verifyEnroll}
                disabled={busy || code.length !== 6}
                style={{ marginTop: 12, width: '100%', background: '#1f3a8a', color: '#fff', border: 'none', borderRadius: 10, padding: '12px 14px', fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer' }}
              >
                {busy ? 'Verifying…' : 'Verify & enable'}
              </button>
            </div>
          </>
        )}

        {/* CTA to start enrollment when not enrolled and no QR shown */}
        {!enrolled && !otpUri && dangerMode === 'none' && (
          <button
            onClick={startEnroll}
            disabled={busy}
            style={{ width: '100%', background: '#1f3a8a', color: '#fff', border: 'none', borderRadius: 10, padding: '12px 14px', fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer' }}
          >
            {busy ? 'Starting…' : 'Set up Authenticator'}
          </button>
        )}
      </div>
    </main>
  );
}