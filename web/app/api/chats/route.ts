import { api } from "@/lib/api";

// Every chat this user had, newest first, with the jobs each one made.
export async function GET() {
  const r = await api("/v1/chats");
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}
