import { api } from "@/lib/api";

// Previews, the GLB for the viewer and the delivered files, streamed through from the API.
export async function GET(_req: Request, ctx: RouteContext<"/api/jobs/[id]/files/[name]">) {
  const { id, name } = await ctx.params;
  const r = await api(`/v1/jobs/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`);
  const headers = new Headers();
  for (const k of ["content-type", "content-length", "content-disposition"]) {
    const v = r.headers.get(k);
    if (v) headers.set(k, v);
  }
  headers.set("Cache-Control", "private, max-age=60");
  return new Response(r.body, { status: r.status, headers });
}
