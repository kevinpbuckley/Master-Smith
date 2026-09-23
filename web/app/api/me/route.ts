import { api } from "@/lib/api";

export async function GET() {
  try {
    const r = await api("/v1/me");
    return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
  } catch (e) {
    return Response.json({ error: `cannot reach the Master Smith API: ${e instanceof Error ? e.message : e}` }, { status: 502 });
  }
}
