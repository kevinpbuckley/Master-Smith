// Server-side calls to the Master Smith Python API. The browser never talks to it directly: every request goes
// through a route handler here, so the API key (if you created one) stays on the server.
const BASE = (process.env.MASTERSMITH_API_URL ?? "http://127.0.0.1:8080").replace(/\/$/, "");

export function apiHeaders(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  if (process.env.MASTERSMITH_API_KEY) h.set("Authorization", `Bearer ${process.env.MASTERSMITH_API_KEY}`);
  return h;
}

export function api(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(BASE + path, { ...init, headers: apiHeaders(init.headers), cache: "no-store" });
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await api(path, init);
  if (!r.ok) throw new Error(`${path}: ${r.status} ${(await r.text()).slice(0, 300)}`);
  return (await r.json()) as T;
}

export type Attachment = { path: string; name: string; kind: "image" | "mesh"; bytes?: number };

export type Providers = {
  fal: { usd: number } | null;
  openrouter: {
    usd: number;
    bought_usd?: number;
    key_usage_today_usd?: number;
    key_usage_week_usd?: number;
    key_usage_month_usd?: number;
    key_limit_usd?: number;
    key_limit_remaining_usd?: number;
  } | null;
  errors: Record<string, string>;
  checked: number;
};

export type TurnData = {
  brief: Record<string, unknown> | null;
  last_job: string | null;
  balance: number;
  providers: Providers | null;
  pictures: string[];             // reference pictures drawn this turn ("/v1/jobs/<id>/files/ref_0.png"), for approval
  reference_job: string | null;   // the approved reference job the next build will seed from
  chat_cost_usd: number;
  tools: { name: string; args: unknown; result: string }[];
};

export type JobView = {
  id: string;
  status: "queued" | "running" | "done" | "failed" | "refused";
  kind: string;
  spec: Record<string, unknown>;
  created: number;
  started: number | null;
  finished: number | null;
  error: string | null;
  log: string[];
  summary: {
    lods?: { triangles: number }[] | null;
    dimensions_m?: number[] | null;
    glass?: unknown;
    review?: { score?: number; verdict?: string; issues?: string[] } | null;
    gate?: { ok: boolean; warnings: string[] } | null;
    bill?: { usd_cost?: number; credits_charged?: number; balance?: number } | null;
    rig?: Record<string, unknown>;
  };
  files: string[];
  previews: string[];
  glb: string | null;
};
