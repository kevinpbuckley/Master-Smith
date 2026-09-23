"use client";

import { useEffect, useState } from "react";
import type { JobView } from "@/lib/api";
import ModelViewer from "./ModelViewer";

const ACTIVE = new Set(["queued", "running"]);

function fileUrl(apiPath: string): string {
  // "/v1/jobs/<id>/files/<name>" -> "/api/jobs/<id>/files/<name>"
  return apiPath.replace(/^\/v1\//, "/api/");
}

// The build dashboard: a strip above the chat that follows the current job. It has a fixed height budget and its
// own scrolling, so a long log or many files never squeeze the conversation. Collapsible to one line.
export default function JobPanel({ jobId }: { jobId: string | null }) {
  const [job, setJob] = useState<JobView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const r = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
        if (!r.ok) throw new Error(`${r.status}`);
        const j = (await r.json()) as JobView;
        if (!alive) return;
        setJob(j);
        setErr(null);
        if (ACTIVE.has(j.status)) timer = setTimeout(poll, 3000);
      } catch (e) {
        if (!alive) return;
        setErr(e instanceof Error ? e.message : String(e));
        timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  if (!jobId) return null;

  const s = job?.summary ?? {};
  const files = job ? job.files.filter((f) => !f.includes("/preview_")) : [];
  const name = job ? String(job.spec?.name ?? "Build") : "Build";
  const status = job?.status ?? "loading";
  const lastLine = job?.log.length ? job.log[job.log.length - 1] : err ? `cannot read job: ${err}` : "loading…";

  return (
    <section className={`dash ${open ? "open" : "closed"}`}>
      <div className="dash-bar" onClick={() => setOpen((o) => !o)} role="button" title={open ? "collapse" : "expand"}>
        <span className="dash-title">
          {name} <span className={`status ${status}`}>{status}</span>
        </span>
        <span className="dash-line mono dim">{open ? job?.id ?? jobId : lastLine}</span>
        <span className="dash-toggle dim">{open ? "▾" : "▸"}</span>
      </div>

      {open && job && (
        <div className="dash-body">
          <div className="dash-visual">
            {job.glb && job.status === "done" ? (
              <ModelViewer src={fileUrl(job.glb)} alt={name} />
            ) : job.previews.length > 0 ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img className="hero" src={fileUrl(job.previews[0])} alt="preview" />
            ) : (
              <div className="viewer placeholder">{ACTIVE.has(job.status) ? "building…" : "no preview"}</div>
            )}
          </div>

          <div className="dash-info">
            {job.error && <pre className="error">{job.error}</pre>}
            {job.previews.length > 0 && (
              <div className="previews">
                {job.previews.map((p) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={p} src={fileUrl(p)} alt={p.split("/").pop()} />
                ))}
              </div>
            )}
            {job.status === "done" && (
              <dl className="facts">
                {s.lods && (
                  <>
                    <dt>LODs</dt>
                    <dd>{s.lods.map((l) => l.triangles.toLocaleString()).join(" / ")} tris</dd>
                  </>
                )}
                {s.dimensions_m && (
                  <>
                    <dt>Size</dt>
                    <dd>{s.dimensions_m.map((d) => d.toFixed(2)).join(" × ")} m</dd>
                  </>
                )}
                {s.review && (
                  <>
                    <dt>Review</dt>
                    <dd>
                      {s.review.score ?? "?"}/10 {s.review.verdict ?? ""}
                      {s.review.issues?.length ? ` — ${s.review.issues.slice(0, 3).join("; ")}` : ""}
                    </dd>
                  </>
                )}
                {s.gate && (
                  <>
                    <dt>Gate</dt>
                    <dd>{s.gate.ok ? "ok" : s.gate.warnings.join("; ")}</dd>
                  </>
                )}
                {s.bill && (
                  <>
                    <dt>Spent</dt>
                    <dd>${(s.bill.usd_cost ?? 0).toFixed(3)} provider cost</dd>
                  </>
                )}
              </dl>
            )}
            {files.length > 0 && (
              <div className="files">
                {files.map((f) => (
                  <a key={f} href={fileUrl(f)} download>
                    {f.split("/").pop()}
                  </a>
                ))}
              </div>
            )}
          </div>

          <div className="dash-log">
            <div className="dim">log</div>
            <pre className="log">{job.log.join("\n")}</pre>
          </div>
        </div>
      )}
    </section>
  );
}
