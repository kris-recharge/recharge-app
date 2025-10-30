export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

export async function POST(req: Request) {
  try {
    const { email } = await req.json();
    if (!email) {
      return NextResponse.json({ error: "Missing email" }, { status: 400 });
    }

    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

    if (!url || !serviceKey) {
      console.error("Missing Supabase env: NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY");
      return NextResponse.json({ error: "Server misconfigured" }, { status: 500 });
    }

    const supabaseAdmin = createClient(url, serviceKey);

    const redirectTo = new URL('/login', req.url).toString();
    const { data, error } = await supabaseAdmin.auth.admin.inviteUserByEmail(email, { redirectTo });

    if (error) {
      console.error("Invite error:", error);
      return NextResponse.json({ error: error.message }, { status: 400 });
    }

    return NextResponse.json({ message: `Invite sent to ${email}`, user: data });
  } catch (err) {
    console.error("Unhandled error:", err);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}