export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

import { NextResponse } from "next/server";
import { getPool } from "@/lib/db";

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