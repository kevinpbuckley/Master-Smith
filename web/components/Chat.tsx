"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Attachment, Providers, TurnData } from "@/lib/api";
import JobPanel from "./JobPanel";

type SmithMessage = UIMessage<unknown, { turn: TurnData }>;

type Me = { user: string; balance: number; local_mode: boolean; providers?: Providers | null; error?: string };

function Accounts({ p }: { p: Providers | null | undefined }) {
  if (!p) return null;
  const cell = (label: string, v: { usd: number } | null, err?: string) =>
    v ? (
      <span className={v.usd < 2 ? "low" : ""} title={err}>
        {label} ${v.usd.toFixed(2)}
      </span>
    ) : (
      <span className="low" title={err}>
        {label} ?
      </span>
    );
  const month = p.openrouter?.key_usage_month_usd;
  return (
    <span className="accounts" title={month !== undefined ? `OpenRouter key: $${month.toFixed(2)} this month` : undefined}>
      {cell("fal", p.fal, p.errors?.fal)} · {cell("OpenRouter", p.openrouter, p.errors?.openrouter)}
    </span>
  );
}

function newSessionId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
}

export default function Chat() {
  const [sessionId, setSessionId] = useState<string>(() => newSessionId());
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<(Attachment & { preview?: string })[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const transport = useMemo(() => new DefaultChatTransport<SmithMessage>({ api: "/api/chat" }), []);
  const { messages, sendMessage, status, error, setMessages } = useChat<SmithMessage>({ id: sessionId, transport });
  const busy = status === "submitted" || status === "streaming";

  useEffect(() => {
    fetch("/api/me", { cache: "no-store" })
      .then((r) => r.json())
      .then(setMe)
      .catch((e) => setMe({ user: "?", balance: 0, local_mode: true, error: String(e) }));
  }, []);

  // the newest turn that queued a job is the one the panel follows; its balance is fresher than /api/me's
  const latest = useMemo(() => {
    let job: string | null = null;
    let balance: number | null = null;
    let providers: Providers | null = null;
    for (let i = messages.length - 1; i >= 0; i--) {
      const turn = messages[i].parts.find((p) => p.type === "data-turn");
      if (turn && turn.type === "data-turn") {
        if (balance === null) balance = turn.data.balance;
        if (!providers) providers = turn.data.providers;
        if (turn.data.last_job) {
          job = turn.data.last_job;
          break;
        }
      }
    }
    return { job, balance, providers };
  }, [messages]);
  const jobId = latest.job;
  const balance = latest.balance ?? me?.balance ?? 0;
  const accounts = latest.providers ?? me?.providers;

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", f, f.name);
        const r = await fetch("/api/upload", { method: "POST", body: fd });
        const j = (await r.json()) as Attachment & { detail?: string; error?: string };
        if (!r.ok) {
          alert(j.detail || j.error || `upload failed (${r.status})`);
          continue;
        }
        const preview = f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined;
        setAttachments((a) => [...a, { path: j.path, name: j.name, kind: j.kind, bytes: j.bytes, preview }]);
      }
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function send() {
    const t = text.trim();
    if ((!t && attachments.length === 0) || busy) return;
    const msg = t || (attachments.some((a) => a.kind === "mesh") ? "Import this model." : "Use these pictures.");
    const label = attachments.length ? `${msg}\n\n📎 ${attachments.map((a) => a.name).join(", ")}` : msg;
    setText("");
    const sent = attachments.map(({ path, name, kind }) => ({ path, name, kind }));
    setAttachments([]);
    await sendMessage({ text: label }, { body: { attachments: sent } });
  }

  function reset() {
    setMessages([]);
    setAttachments([]);
    setSessionId(newSessionId());
  }

  return (
    <div className="shell">
      <header className="top">
        <div>
          <h1>Master Smith</h1>
          <p className="dim">Prompt in, game-ready 3D model out. Describe an asset, or attach a model to finish it.</p>
        </div>
        <div className="me">
          {me?.error ? (
            <span className="error-inline">API offline: {me.error}</span>
          ) : me ? (
            <span className="dim">
              <Accounts p={accounts} />
              {accounts ? " · " : ""}
              {me.user}
              {me.local_mode ? " (local)" : ""} · spent here ${(-balance / 100).toFixed(2)}
            </span>
          ) : null}
          <button className="ghost" onClick={reset} disabled={busy}>
            New chat
          </button>
        </div>
      </header>

      <main className="stack">
        <JobPanel jobId={jobId} />
        <section className="chat">
          <div className="log">
            {messages.length === 0 && (
              <div className="msg assistant">
                <p>
                  Tell me what to build: what it is, its materials and colours, how big it is, and which engine. I will
                  write the brief, quote the worst-case cost, and start when you say go. Attach a <code>.glb</code>,{" "}
                  <code>.fbx</code>, <code>.obj</code> or <code>.blend</code> to finish a model you already have.
                </p>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.role}`}>
                {m.parts.map((p, i) => {
                  if (p.type === "text") return <p key={i}>{p.text}</p>;
                  if (p.type === "data-turn")
                    return (
                      <div key={i}>
                        {p.data.pictures?.length > 0 && (
                          <Pictures
                            urls={p.data.pictures}
                            onApprove={() => sendMessage({ text: "Go: build from this picture." })}
                            onChange={() => document.querySelector<HTMLTextAreaElement>(".composer textarea")?.focus()}
                            busy={busy}
                          />
                        )}
                        <TurnCard turn={p.data} />
                      </div>
                    );
                  return null;
                })}
              </div>
            ))}
            {busy && <div className="msg assistant dim">thinking…</div>}
            {error && <div className="msg error">{error.message}</div>}
            <div ref={bottom} />
          </div>

          <form
            className={`composer${dragging ? " dragging" : ""}`}
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              upload(e.dataTransfer.files);
            }}
          >
            {attachments.length > 0 && (
              <div className="chips">
                {attachments.map((a) => (
                  <span key={a.path} className="chip">
                    {a.preview ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={a.preview} alt="" />
                    ) : (
                      "🧊"
                    )}{" "}
                    {a.name}
                    <button type="button" onClick={() => setAttachments((x) => x.filter((y) => y.path !== a.path))}>
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="row">
              <input
                ref={fileInput}
                type="file"
                multiple
                accept=".png,.jpg,.jpeg,.webp,.glb,.gltf,.fbx,.obj,.blend"
                onChange={(e) => upload(e.target.files)}
                hidden
                id="file"
              />
              <button type="button" className="ghost" onClick={() => fileInput.current?.click()} disabled={uploading || busy}>
                {uploading ? "uploading…" : "Attach"}
              </button>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                onPaste={(e) => {
                  const files = Array.from(e.clipboardData.items)
                    .filter((it) => it.kind === "file")
                    .map((it) => it.getAsFile())
                    .filter((f): f is File => !!f);
                  if (files.length) {
                    e.preventDefault();
                    const dt = new DataTransfer();
                    files.forEach((f) => dt.items.add(f));
                    upload(dt.files);
                  }
                }}
                placeholder="a weathered oak ammunition crate with rope handles and black stencils, 1.2 m, Unreal — or drop / paste pictures and model files here"
                rows={2}
              />
              <button type="submit" disabled={busy || uploading}>
                Send
              </button>
            </div>
          </form>
        </section>
      </main>
    </div>
  );
}

function Pictures({
  urls,
  onApprove,
  onChange,
  busy,
}: {
  urls: { label: string; url: string }[];
  onApprove: () => void;
  onChange: () => void;
  busy: boolean;
}) {
  return (
    <div className="pictures">
      <div className="pictures-row">
        {urls.map((p, i) => {
          const src = p.url.replace(/^\/v1\//, "/api/");
          const caption = i === 0 ? "reference" : p.label.replace(/^orthographic /, "");
          return (
            <figure key={p.url}>
              <a href={src} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={src} alt={p.label} title={p.label} />
              </a>
              <figcaption className="dim">{caption}</figcaption>
            </figure>
          );
        })}
      </div>
      <div className="pictures-actions">
        <button type="button" onClick={onApprove} disabled={busy}>
          Build from this
        </button>
        <button type="button" className="ghost" onClick={onChange} disabled={busy}>
          Change something…
        </button>
        <span className="dim">The mesh is bought only after you approve the picture.</span>
      </div>
    </div>
  );
}

function TurnCard({ turn }: { turn: TurnData }) {
  const b = turn.brief;
  const tools = turn.tools.filter((t) => t.name !== "balance");
  if (!b && tools.length === 0) return null;
  return (
    <details className="turn">
      <summary>
        {b ? `Brief: ${String(b.name)} · ${String(b.category)} · ${String(b.style)} · ${Number(b.tri_budget).toLocaleString()} tris · ${Number(b.size_m) > 0 ? `${b.size_m} m` : "source size"}` : "tools"}
        {turn.last_job ? ` · job ${turn.last_job}` : ""}
        {` · chat $${turn.chat_cost_usd.toFixed(4)}`}
      </summary>
      {tools.map((t, i) => (
        <div key={i} className="tool">
          <code>{t.name}</code> <span className="dim">{JSON.stringify(t.args).slice(0, 240)}</span>
          <div className="dim mono">{t.result}</div>
        </div>
      ))}
    </details>
  );
}
