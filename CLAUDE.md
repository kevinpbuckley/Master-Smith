@AGENTS.md

# Claude Code specifics

- The build recipe is the `forge` skill: `/forge <what to make>` (`.claude/skills/forge/SKILL.md`).
- Commit messages end with the `Co-Authored-By: Claude <model> <noreply@anthropic.com>` line of the model in use
  (as the session's attribution reminder gives it).
- Look at pictures and renders with the Read tool; it shows the image. Never print secrets from `.env`.
- Write a script or a patch with the Write/Edit tools and run the file: quoted multi-line heredocs in the Bash tool
  broke about eleven times on 2026-09-29/10-01 (nested quotes, `\a` in a Windows path turned into a bell). Bash's
  `sleep` is blocked: run long commands with `run_in_background` and wait for the notification.
- Long runs (an assemble, a batch) go in the background; say so in one line with what to expect, and answer the owner
  before the next tool call (AGENTS.md rule 12).
