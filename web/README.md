# Master Smith chat

The chat interface: a Next.js app on the Vercel AI SDK. It talks to the Python API in the repository root through
its own route handlers (`app/api/*`), so an API key, if you created one, never reaches the browser.

```bash
npm ci
cp .env.example .env.local      # MASTERSMITH_API_URL, default http://127.0.0.1:8080
npm run dev                     # http://localhost:3000
```

- `components/Chat.tsx` – `useChat` over `DefaultChatTransport`; uploads go to `/api/upload` first and are sent as
  `attachments` in the request body.
- `app/api/chat/route.ts` – forwards the newest user message to `POST /v1/chat` and answers with a UI message
  stream: the reply text, then a `data-turn` part (brief, queued job id, spend, tool calls).
- `components/JobPanel.tsx` – polls `/api/jobs/<id>` while a build runs; previews, facts, files, and the finished
  GLB in Google's `<model-viewer>`.

`npm run build` uses `output: "standalone"` for `Dockerfile`; use `npm run dev` locally.
