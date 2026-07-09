# Contributing

Thanks for your interest. PRs are welcome — especially:

- **New ATS adapters** (see [docs/ATS_SUPPORT.md](docs/ATS_SUPPORT.md))
- **Prompt improvements** in `src/llm/prompts/`
- **Pre-flight checks** in `src/orchestrator/preflight.py`
- **More email providers** in `docs/RUNBOOK.md`
- **Bug fixes** with a regression test

## Setup

```bash
git clone https://github.com/drajb/Job-Application-Automation.git
cd Job-Application-Automation
make dev-install
make test
```

You should see 55+ tests pass.

## Workflow

1. Open an issue describing what you're proposing (or comment on an existing one).
2. Fork → branch → PR.
3. Keep PRs small and focused. One ATS adapter per PR.
4. Add tests. Pure-logic changes → unit tests. Adapter changes → at least the `can_handle` / detector test.
5. Run `make lint` and `make test` locally.
6. Open the PR against `main`.

## What gets rejected

- Anything that adds OpenAI, Anthropic, or any other paid LLM provider. The locked spec is Gemini-only. Add a TODO comment in `docs/SPEC.md §9` and we can discuss before code.
- Anything that weakens the resume validator (`src/resume/validator.py`). The validator is sacred — its job is to reject creative paraphrase that drifts into fabrication. If it false-positives, **add to the test suite to show the false positive**, then we can extend the allowlist together.
- Changes that remove `dry_run=True` as the default.
- Any code path that automatically submits a LinkedIn Easy Apply form. LinkedIn is Tier-3 manual takeover only.
- PRs that mix multiple changes (refactor + feature + bugfix in one diff). Split them.

## Adding a new ATS adapter

The shortest path:

1. Read [src/ats/base.py](../src/ats/base.py) — that's the contract.
2. Read [src/ats/greenhouse.py](../src/ats/greenhouse.py) as a worked example.
3. Add your file under `src/ats/`. Implement `can_handle`, `parse_job`, `fill`.
4. Register the URL pattern in `src/ats/detector.py`.
5. Wire `adapter_for()` to return your class.
6. Add a smoke test in `tests/test_phase4.py` (or a new file) — at minimum: URL detection, `can_handle()` returns True for canonical URL, False for others.
7. Open a PR. If you have a live test URL, mention it.

Selectors will rot. That's fine. We use defensive selectors (`.x, .y, .z` alternates) and let things skip gracefully.

## Style

- Ruff for lint: `make lint`.
- Type hints on public functions. Private helpers are optional.
- One short module docstring per file. Comments only where the *why* is non-obvious.
- No comments referring to "Phase N" inside the code (that's spec-internal). Reference [docs/SPEC.md](docs/SPEC.md) sections by number if you must.

## Commit messages

- Imperative first line, ≤72 chars.
- Body explains *why*, not *what*.

```
Add Workday Tier-1 adapter

Workday is the most-requested ATS missing from Tier-1. This adapter
covers the standard myworkdayjobs.com flow. Captchas still escalate
to Tier-3.
```

## Code of Conduct

Be kind. Be specific. Assume good faith. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
