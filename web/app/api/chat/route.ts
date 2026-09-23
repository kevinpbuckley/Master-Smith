import { createUIMessageStream, createUIMessageStreamResponse, type UIMessage } from "ai";
import { api, type Attachment, type TurnData } from "@/lib/api";

// One chat turn. The Vercel AI SDK client posts the whole conversation; the director on the Python side keeps its
// own transcript per session, so only the newest user message (plus any attachments) is forwarded. The reply comes
// back as a UI message stream: the text, then a `data-turn` part with the brief, the queued job and the spend.
export async function POST(req: Request) {
  const body = (await req.json()) as { id?: string; messages: UIMessage[]; attachments?: Attachment[] };
  const last = [...(body.messages ?? [])].reverse().find((m) => m.role === "user");
  const text = (last?.parts ?? [])
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("\n")
    .trim();
  const sessionId = body.id ?? "default";
  const attachments = body.attachments ?? [];

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      writer.write({ type: "start" });
      const r = await api("/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId, attachments }),
      });
      if (!r.ok) {
        const detail = (await r.text()).slice(0, 400);
        writer.write({ type: "error", errorText: `Master Smith API answered ${r.status}: ${detail}` });
        writer.write({ type: "finish" });
        return;
      }
      const j = (await r.json()) as { reply: string } & TurnData;
      const id = `t-${Date.now()}`;
      writer.write({ type: "text-start", id });
      writer.write({ type: "text-delta", id, delta: j.reply || "(no reply)" });
      writer.write({ type: "text-end", id });
      const turn: TurnData = {
        brief: j.brief ?? null,
        last_job: j.last_job ?? null,
        balance: j.balance,
        chat_cost_usd: j.chat_cost_usd,
        tools: j.tools ?? [],
      };
      writer.write({ type: "data-turn", data: turn });
      writer.write({ type: "finish" });
    },
    onError: (e) => (e instanceof Error ? e.message : String(e)),
  });
  return createUIMessageStreamResponse({ stream });
}
