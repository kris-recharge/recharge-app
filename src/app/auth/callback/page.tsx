// Server component: handle Supabase OAuth/recovery callback and bounce to the right screen
export const dynamic = 'force-dynamic';
export const revalidate = 0; // ok on server components

const PORTAL_V2 = process.env.NEXT_PUBLIC_PORTAL_V2_URL ?? 'https://recharge-portal-v2.onrender.com';

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
      const PORTAL_V2 = '${PORTAL_V2}';
      const url = new URL(window.location.href);

      // Helper: keep only internal next= paths or URLs starting with PORTAL_V2
      const pickSafeNext = (candidate) => {
        if (!candidate) return '';
        try {
          if (candidate.startsWith('/')) return candidate;
          if (candidate.startsWith(PORTAL_V2)) return candidate;
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

      // 3) If Supabase handed us an access token (magiclink/sign-in), go straight to v2 WITH ?sb=
      if (url.hash && (url.hash.includes('access_token=') || url.hash.includes('token='))) {
        const hash = new URLSearchParams(url.hash.substring(1));
        const at = hash.get('access_token') || hash.get('token');
        if (at) {
          const nextAbs = pickSafeNext(
            url.searchParams.get('redirect_to') || url.searchParams.get('next') || hash.get('redirect_to') || hash.get('next')
          );
          // Build destination base (either absolute to v2 or leave as provided if it already targets v2)
          const destBase = nextAbs
            ? (nextAbs.startsWith('/') ? (PORTAL_V2 + nextAbs) : nextAbs)
            : PORTAL_V2;
          const out = new URL(destBase);
          // Append sb token so Streamlit can mint its own session
          if (!out.searchParams.get('sb')) out.searchParams.set('sb', at);
          window.location.replace(out.toString());
          return;
        }
      }

      // 4) Error cases from Supabase
      const err = url.searchParams.get('error') || url.searchParams.get('error_code');
      if (err) {
        window.location.replace('/login?error=' + encodeURIComponent(err));
        return;
      }

      // 5) Fallback: go back to login
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