# Contributing

Master Smith is the open-source edition of the pipeline behind a commercial product. Improvements land here first
and are carried across, so a pull request here can end up in production. Thank you for that.

## What helps most

- **Quality of the models.** Better reference pictures, better seed vendor settings, smarter Blender finishing
  (glass, cockpits, wheels, part seeds, decimation, baking). Measure before and after on the same brief and put
  the renders in the PR.
- **New categories.** A skill is a Markdown file in `mastersmith/skills/` with front matter the pipeline reads.
  See the README section "Adding a skill or a vendor".
- **New vendors.** One row in `mastersmith/pricing.py` and a call site in a stage. Unpriced endpoints are refused
  on purpose, so the row is not optional.
- **Engine importers.** `mastersmith/stages/package.py` writes the import notes; Unity and Godot get less love
  than Unreal today.
- **The chat.** `web/` is a Next.js app on the Vercel AI SDK; the director itself is Python (`mastersmith/agent.py`).

## Branches

`master` is what people run; `dev` is where work lands. Open pull requests against `dev`. When `dev` is verified
end to end (a real build through the containers), it is merged into `master`.

## Running the tests

```bash
python -m pytest -q tests/test_core.py tests/test_syntax.py       # pure tests, no keys, a second
MASTERSMITH_BLENDER_TESTS=1 python -m pytest -q tests/test_blender_synthetic.py   # needs Blender, about a minute
cd web && npm run build && npm run lint
```

A build that reaches fal or OpenRouter spends real money on your keys. Keep live runs out of tests.

## Style

Python: four-space indentation, one job per module, comments that say *why* (many carry the date and the asset that
taught the lesson; keep doing that). No formatter is enforced; `ruff`-clean is welcome. TypeScript: the scaffold's
ESLint config.

## Secrets

`.env` is ignored and must stay that way. Never paste a key, a signed URL or a customer picture into an issue.

## Relationship to the upstream product

The upstream package is named `anvil`; this one is `mastersmith`. A change ported upstream is the same diff with
`mastersmith` → `anvil` and `MASTERSMITH_` → `ANVIL_`, so keep imports relative (`from . import config`) and read
settings through `config` rather than `os.environ` where you can. Blender datablock names inside delivered
`.blend` files (`anvil_spec.json`, `anvil_reference`, `anvil_mask`, …) are kept as they are so files move between
the two without conversion; do not rename them.
