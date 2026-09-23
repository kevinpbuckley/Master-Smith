import { api } from "@/lib/api";

export async function GET() {
  const r = await api("/v1/jobs");
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}
