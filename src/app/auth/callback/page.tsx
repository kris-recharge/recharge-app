// Server component: handle Supabase OAuth/recovery callback and bounce to the right screen
export const dynamic = 'force-dynamic';
export const revalidate = 0; // ok on server components

export default function AuthCallback() {
  // Keep typing simple so we don't need to import React types on the server
  const pageStyle = {
    minHeight: '100vh',
    display: 'grid',
    placeItems: 'center',
    color: '#94a3b8',
  } as const;

  // We purposely do *not* use hooks here. This page renders on the server,
  // and then the inline script runs in the browser to parse URL params/hash
  // and redirect to the appropriate flow.
  const script = `(() => {
    try {
      const url = new URL(window.location.href);

      // Helper: keep only internal next= paths
      const pickSafeNext = (candidate) => {
        if (!candidate) return '';
        try {
          // Allow only "/..." relative paths; drop protocol/hosted URLs
          if (candidate.startsWith('/')) return candidate;
        } catch (_) {}
        return '';
      };

      const nextFromQuery = pickSafeNext(url.searchParams.get('redirect_to') || url.searchParams.get('redirect') || url.searchParams.get('next'));

      // 1) PKCE/code flow (?code=...)
      const code = url.searchParams.get('code');
      if (code) {
        const dest = '/reset-password?code=' + encodeURIComponent(code) + (nextFromQuery ? '&next=' + encodeURIComponent(nextFromQuery) : '');
        window.location.replace(dest);
        return;
      }

      // 2) Hash-based recovery: #access_token=...&refresh_token=...&type=recovery[&redirect_to=/foo]
      if (url.hash && url.hash.startsWith('#')) {
        const hash = new URLSearchParams(url.hash.substring(1));
        const type = hash.get('type');
        const at = hash.get('access_token');
        const rt = hash.get('refresh_token');
        const nextFromHash = pickSafeNext(hash.get('redirect_to') || hash.get('next'));
        if (type === 'recovery' && at && rt) {
          const nextHash = new URLSearchParams({ type: 'recovery', access_token: at, refresh_token: rt }).toString();
          const suffix = nextFromHash ? ('?next=' + encodeURIComponent(nextFromHash)) : '';
          window.location.replace('/reset-password' + suffix + '#' + nextHash);
          return;
        }
      }

      // 3) Error cases from Supabase
      const err = url.searchParams.get('error') || url.searchParams.get('error_code');
      if (err) {
        window.location.replace('/login?error=' + encodeURIComponent(err));
        return;
      }

      // 4) Fallback: go back to login
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