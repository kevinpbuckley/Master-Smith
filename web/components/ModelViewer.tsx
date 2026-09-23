"use client";

import { createElement, useEffect, useState } from "react";

// Google's <model-viewer> web component, loaded from a CDN on first use. Rendered through createElement so the
// custom element needs no JSX type declarations.
let loading: Promise<void> | null = null;
function loadModelViewer(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (customElements.get("model-viewer")) return Promise.resolve();
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.type = "module";
      s.src = "https://cdn.jsdelivr.net/npm/@google/model-viewer@4.1.0/dist/model-viewer.min.js";
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("model-viewer failed to load"));
      document.head.appendChild(s);
    });
  }
  return loading;
}

export default function ModelViewer({ src, alt }: { src: string; alt: string }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    loadModelViewer().then(() => alive && setReady(true)).catch(() => alive && setReady(false));
    return () => {
      alive = false;
    };
  }, []);
  if (!ready) return <div className="viewer placeholder">loading viewer…</div>;
  return createElement("model-viewer", {
    src,
    alt,
    "camera-controls": "",
    "auto-rotate": "",
    "shadow-intensity": "1",
    exposure: "1",
    class: "viewer",
    style: { width: "100%", height: "320px", background: "var(--panel-2)", borderRadius: "10px" },
  });
}
