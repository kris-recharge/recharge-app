'use client';

export default function EnvDebug() {
  // This is replaced at build/dev time because the key starts with NEXT_PUBLIC_
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;

  console.log('EnvDebug – NEXT_PUBLIC_SUPABASE_URL =', url);

  return (
    <main style={{padding: 24}}>
      <h1>Env Debug</h1>
      <p><strong>NEXT_PUBLIC_SUPABASE_URL:</strong> {url ?? 'MISSING'}</p>
      <p>If this shows your Supabase URL and the console logs it too, env is wired correctly.</p>
    </main>
  );
}