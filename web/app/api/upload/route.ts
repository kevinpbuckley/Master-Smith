import { api } from "@/lib/api";

// A picture or a model file from the browser, handed to the API's upload store. The reply carries the path the
// chat puts in its attachments.
export async function POST(req: Request) {
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return Response.json({ error: "no file" }, { status: 400 });
  const out = new FormData();
  out.append("file", file, file.name);
  const r = await api("/v1/uploads", { method: "POST", body: out });
  const text = await r.text();
  return new Response(text, { status: r.status, headers: { "Content-Type": "application/json" } });
}
