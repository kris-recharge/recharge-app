import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { Pool } from "pg";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_ANON_KEY!
);

const pool = new Pool({
  connectionString: process.env.DATABASE_URL!,
  ssl: { rejectUnauthorized: false },
});

export async function POST(req: Request) {
  const { supabase_uid, email } = await req.json();

  if (!supabase_uid || !email) {
    return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  }

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

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("bootstrap error:", err);
    return NextResponse.json({ error: "DB insert failed" }, { status: 500 });
  } finally {
    client.release();
  }
}