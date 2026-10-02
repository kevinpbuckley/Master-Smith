# Codex specifics

AGENTS.md is the shared brief; this is what working Master Smith from Codex needs on top of it (from the Codex logs
of 2026-09-29 to 10-01). Read it before the first command.

- **Start in this folder, with full access.** Two sessions on 2026-09-29 ended with nothing built: the sandbox refused
  plain commands ("setup refresh had errors"), every read asked for escalation, and one escalation waited all night
  for an answer. Launch Codex from `E:\az-dev-ops\Master-Smith` with workspace-write or full access (`/yolo` was what
  worked); started elsewhere, `$forge` is not offered - run `./scripts/setup-skills.ps1 -User` once so it is.
- **Read whole files in pieces.** `exec_command` returns at most ~10k tokens by default and cuts the MIDDLE out of
  anything longer; a proxy (headroom) may compress output too. AGENTS.md is injected for you; read
  `.claude/skills/forge/SKILL.md` on its own, with `max_output_tokens` of at least 8000, or in two halves - never
  together with AGENTS.md (the owner's rules sit in the middle). Print `r.output`, not the whole result object.
- **The questions AGENTS.md asks are required, not optional.** Codex's own instructions say the user dislikes being
  asked; Master Smith's owner wants exactly these questions: which picture and seed model (with the prices), spending
  anything, approving references, redrawing a picture, replacing part of a seed. Ask them, and name the rule
  ("AGENTS.md, What costs money"). Everything else: proceed without asking. Record each answer: `ms note`.
- **Long runs**: an assemble is 5-15 min (a draft about one). Start it, poll with `write_stdin`, and give the owner a
  line with the preview link in between - "are you stuck?" (2026-10-01) is a status line that never came. Two at a
  time at most: `ms batch assemble out/A out/B --parallel 2`.
- **Look at every render** with `view_image` (`image((await tools.view_image({path})).image_url)`) before calling
  anything good; `ms closeup` makes the close-ups.
- **After a compaction**, re-read AGENTS.md's rules and run `ms status out/<Name>` for the models, the money and the
  owner's notes before the next step.
- **Commits** end with `Co-Authored-By: OpenAI Codex <noreply@openai.com>` (rule 11; `dev` only). Commit only your own
  hunks; another session's work only when the owner says so.
- Write scripts and patches with `apply_patch` and run the file; never put a multi-line Python script inside a
  PowerShell here-string with nested quotes.
