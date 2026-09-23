import { api } from "@/lib/api";

// Mesh vendors, director models and the picture models in force, for the header's selectors.
export async function GET() {
  const r = await api("/v1/models");
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}
