import { api } from "@/lib/api";

// Mesh vendors, director models with OpenRouter's prices, and the picture models in force, for the header's
// selectors. ?all=1 lists every tool-and-vision-capable model OpenRouter serves.
export async function GET(req: Request) {
  const all = new URL(req.url).searchParams.get("all") === "1";
  const r = await api(`/v1/models${all ? "?all=1" : ""}`);
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}
