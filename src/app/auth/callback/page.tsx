// Server component: handle Supabase OAuth/recovery callback and bounce to the right screen
export const dynamic = 'force-dynamic';
export const revalidate = 0; // ok on server components

export default function AuthCallback() {
  const pageStyle: React.CSSProperties = {
    minHeight: '100vh',
    display: 'grid',
    placeItems: 'center',
    color: '#94a3b8',
  };

  // We purposely do *not* use hooks here. This page renders on the server,
  // and then the inline script runs in the browser to parse URL params/hash
  // and redirect to the appropriate flow.
  const script = `(() => {
    try {
      const url = new URL(window.location.href);
      const code = url.searchParams.get('code');
      if (code) {
        // PKCE flow -> let the reset page complete the exchange via Supabase API
        window.location.replace('/reset-password?code=' + encodeURIComponent(code));
        return;
      }

      // Hash-based recovery: #access_token=...&refresh_token=...&type=recovery
      if (url.hash && url.hash.startsWith('#')) {
        const hash = new URLSearchParams(url.hash.substring(1));
        const type = hash.get('type');
        const at = hash.get('access_token');
        const rt = hash.get('refresh_token');
        if (type === 'recovery' && at && rt) {
          // hand tokens to the reset page via hash
          const nextHash = new URLSearchParams({ type: 'recovery', access_token: at, refresh_token: rt }).toString();
          window.location.replace('/reset-password#' + nextHash);
          return;
        }
      }

      // Fallback: go back to login
      window.location.replace('/login');
    } catch (e) {
      console.error(e);
      window.location.replace('/login');
    }
  })();`;

  return (
    <main style={pageStyle}>
      Processing…
      <script dangerouslySetInnerHTML={{ __html: script }} />
    </main>
  );
}