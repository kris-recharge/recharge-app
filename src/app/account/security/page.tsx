'use client';
import { useEffect, useState } from 'react';
import { createClient } from '@/lib/supabaseClient';

export default function SecurityPage() {
  const supabase = createClient();
  const [enrolled, setEnrolled] = useState(false);
  const [factorId, setFactorId] = useState<string | null>(null);
  const [otpUri, setOtpUri] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const { data, error } = await supabase.auth.mfa.listFactors();
      if (!error && data?.all?.some(f => f.factorType === 'totp' && f.status === 'verified')) {
        setEnrolled(true);
      }
    })();
  }, []);

  async function startEnroll() {
    setMsg(null);
    const { data, error } = await supabase.auth.mfa.enroll({ factorType: 'totp' });
    if (error) { setMsg(error.message); return; }
    setFactorId(data.id);
    setOtpUri(data.totp?.uri ?? null);
  }

  async function verify() {
    if (!factorId) return;
    const { error } = await supabase.auth.mfa.verify({ factorId, code, type: 'totp' });
    if (error) { setMsg(error.message); return; }
    setMsg('✅ Authenticator added.');
    setEnrolled(true);
  }

  return (
    <main style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',padding:24,background:'#eef1f5'}}>
      <div style={{background:'#fff',padding:24,borderRadius:12,width:'100%',maxWidth:520,boxShadow:'0 10px 15px -3px rgba(0,0,0,0.1)'}}>
        <h1 style={{fontSize:20,fontWeight:700,marginBottom:8,color:'#0b1830'}}>Account security</h1>
        <p style={{marginBottom:16,color:'#334155'}}>Protect your account with a one-time code from an authenticator app.</p>

        {msg && <div style={{marginBottom:12,color:msg.startsWith('✅') ? '#166534' : '#991b1b'}}>{msg}</div>}

        {enrolled ? (
          <div>✅ TOTP is enabled for this account.</div>
        ) : otpUri ? (
          <>
            <p style={{margin:'12px 0'}}>Scan this QR in Google Authenticator / 1Password / Authy:</p>
            {/* Simple img QR via API (or swap to any QR lib) */}
            <img
              src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(otpUri)}`}
              alt="TOTP QR"
              width={180} height={180}
              style={{border:'1px solid #e2e8f0',borderRadius:8}}
            />
            <div style={{marginTop:12}}>
              <label style={{display:'block',fontSize:14,marginBottom:6}}>6-digit code</label>
              <input value={code} onChange={e=>setCode(e.target.value)} placeholder="123456"
                style={{width:'100%',border:'1px solid #cbd5e1',borderRadius:8,padding:'10px 12px'}} />
              <button onClick={verify} style={{marginTop:12,width:'100%',background:'#1f3a8a',color:'#fff',border:'none',borderRadius:10,padding:'12px 14px',fontWeight:600}}>
                Verify & Enable
              </button>
            </div>
          </>
        ) : (
          <button onClick={startEnroll} style={{width:'100%',background:'#1f3a8a',color:'#fff',border:'none',borderRadius:10,padding:'12px 14px',fontWeight:600}}>
            Set up Authenticator
          </button>
        )}
      </div>
    </main>
  );
}