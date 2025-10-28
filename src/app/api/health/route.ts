export async function GET() {
  return new Response(JSON.stringify({ ok: true, ts: new Date().toISOString() }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
