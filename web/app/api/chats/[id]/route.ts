import { api } from "@/lib/api";

// One chat: its turns, brief, settings and the jobs it made with their files. Loading it warms the API session.
export async function GET(_req: Request, ctx: RouteContext<"/api/chats/[id]">) {
  const { id } = await ctx.params;
  const r = await api(`/v1/chats/${encodeURIComponent(id)}`);
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}

export async function DELETE(_req: Request, ctx: RouteContext<"/api/chats/[id]">) {
  const { id } = await ctx.params;
  const r = await api(`/v1/chats/${encodeURIComponent(id)}`, { method: "DELETE" });
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}
