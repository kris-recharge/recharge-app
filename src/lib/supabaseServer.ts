import { cookies, type ReadonlyRequestCookies } from 'next/headers';
import { createServerClient } from '@supabase/ssr';

export function createServerSupabase() {
  // In Next.js 16, cookies() is synchronous and returns ReadonlyRequestCookies.
  // Explicitly annotate to avoid any accidental Promise<> inference.
  const cookieStore: ReadonlyRequestCookies = cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return cookieStore.get(name)?.value;
        },
        set(name: string, value: string, options: any) {
          // Use the classic signature for cookieStore.set
          cookieStore.set(name, value, options);
        },
        remove(name: string, options: any) {
          // Emulate remove by setting an expired cookie
          cookieStore.set(name, '', { ...options, expires: new Date(0) });
        },
      },
    }
  );
}