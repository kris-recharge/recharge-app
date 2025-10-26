import { cookies } from 'next/headers';
import { createServerClient } from '@supabase/ssr';

export function createServerSupabase() {
  // Use ReturnType<typeof cookies> so we don't rely on unstable exported types.
  const cookieStore: ReturnType<typeof cookies> = cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return cookieStore.get(name)?.value;
        },
        set(name: string, value: string, options: any) {
          cookieStore.set(name, value, options);
        },
        remove(name: string, options: any) {
          cookieStore.set(name, '', { ...options, expires: new Date(0) });
        },
      },
    }
  );
}