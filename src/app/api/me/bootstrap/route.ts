import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { getPool } from "@/lib/db";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_ANON_KEY!
);

export async function POST(req: Request) {
  try {
    const { supabase_uid, email } = await req.json();

    if (!supabase_uid || !email) {
      return NextResponse.json({ error: "Missing fields" }, { status: 400 });
    }

    const pool = getPool();
    const client = await pool.connect();

    try {
      await client.query(
        `
        INSERT INTO app_users (supabase_uid, email)
        VALUES ($1, $2)
        ON CONFLICT (email) DO NOTHING;
        `,
        [supabase_uid, email]
      );
    } finally {
      client.release();
    }

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("bootstrap error:", err);
    return NextResponse.json({ error: "DB insert failed" }, { status: 500 });
  }
}