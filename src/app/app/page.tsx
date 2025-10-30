'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabaseClient';

export default function AppHome() {
  const router = useRouter();
  const supabase = createClient();
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data?.session) {
        router.replace('/login');
        return;
      }
      setEmail(data.session.user.email ?? null);
      setReady(true);
    })();
  }, [router, supabase]);

  if (!ready) {
    return (
      <main style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',color:'#94a3b8'}}>
        Loading…
      </main>
    );
  }

  return (
    <main style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',background:'#0b1830',color:'white',padding:24}}>
      <div style={{maxWidth:720,width:'100%',background:'#0f1b36',border:'1px solid #233157',borderRadius:12,padding:24}}>
        <h1 style={{marginTop:0}}>ReCharge Alaska Portal</h1>
        <p style={{opacity:.85}}>Signed in as <b>{email ?? 'user'}</b></p>
        <div style={{marginTop:16,display:'flex',gap:12}}>
          <button
            onClick={async () => {
              await supabase.auth.signOut();
              router.replace('/login');
            }}
            style={{background:'#e11d48',border:'none',color:'#fff',padding:'10px 14px',borderRadius:8,cursor:'pointer'}}
          >
            Sign out
          </button>
          <a href="/account/security" style={{color:'#93c5fd'}}>Account security →</a>
        </div>
      </div>
    </main>
  );
}