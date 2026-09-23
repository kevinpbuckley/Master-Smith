import { api } from "@/lib/api";

export async function GET(_req: Request, ctx: RouteContext<"/api/jobs/[id]">) {
  const { id } = await ctx.params;
  const r = await api(`/v1/jobs/${encodeURIComponent(id)}`);
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}
