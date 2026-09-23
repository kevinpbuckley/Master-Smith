"use client";

import { useEffect, useState } from "react";
import type { JobView } from "@/lib/api";
import ModelViewer from "./ModelViewer";

const ACTIVE = new Set(["queued", "running"]);

function fileUrl(apiPath: string): string {
  // "/v1/jobs/<id>/files/<name>" -> "/api/jobs/<id>/files/<name>"
  return apiPath.replace(/^\/v1\//, "/api/");
}

export default function JobPanel({ jobId }: { jobId: string | null }) {
  const [job, setJob] = useState<JobView | null>(null);
  const [err, setErr] = useState<string | null>(null);

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

  if (!jobId) {
    return (
      <aside className="panel">
        <h2>Build</h2>
        <p className="dim">Nothing queued yet. Describe an asset, or attach a model file to bring one in.</p>
      </aside>
    );
  }
  if (!job) {
    return (
      <aside className="panel">
        <h2>Build</h2>
        <p className="dim">{err ? `cannot read job: ${err}` : "loading…"}</p>
      </aside>
    );
  }
  const s = job.summary ?? {};
  const files = job.files.filter((f) => !f.includes("/preview_"));
  return (
    <aside className="panel">
      <h2>
        {String(job.spec?.name ?? "Build")} <span className={`status ${job.status}`}>{job.status}</span>
      </h2>
      <p className="dim mono">
        {job.kind} · {job.id}
      </p>
      {job.error && <pre className="error">{job.error}</pre>}

      {job.glb && job.status === "done" && <ModelViewer src={fileUrl(job.glb)} alt={String(job.spec?.name ?? "model")} />}

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
          <h3>Files</h3>
          {files.map((f) => (
            <a key={f} href={fileUrl(f)} download>
              {f.split("/").pop()}
            </a>
          ))}
        </div>
      )}

      {job.log.length > 0 && (
        <details open={ACTIVE.has(job.status)}>
          <summary>Log</summary>
          <pre className="log">{job.log.join("\n")}</pre>
        </details>
      )}
    </aside>
  );
}
