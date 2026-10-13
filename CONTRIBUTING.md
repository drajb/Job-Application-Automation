# Contributing

PRs are welcome, especially:

- **New ATS adapters** and selector fixes (see [docs/ATS_SUPPORT.md](docs/ATS_SUPPORT.md))
- **Validator test cases**: a fabrication that slips through, or a legitimate rewrite that's rejected
- **Prompt improvements** in `src/llm/prompts/`
- **Job-board sources** for discovery in `src/discovery/boards.py`
- **Bug fixes** with a regression test

## Setup

```bash
git clone https://github.com/drajb/Job-Application-Automation.git
cd Job-Application-Automation
make dev-install
make check        # ruff + mypy + pytest, same as CI
```

Everything runs offline; tests fake the browser, Gemini and Telegram.

## Workflow

1. Open an issue (or comment on one) describing the change.
2. Fork → branch → PR against `main`. One change per PR.
3. Add tests. `make check` must pass.
4. If you change a model in `src/db/models.py`, add an Alembic migration. CI fails when models and migrations disagree.

## What gets rejected

- Other LLM providers (OpenAI, Anthropic, ...). Gemini only, to keep the runtime free.
- Weakening the resume validator. If it flags something legitimate, add a failing test showing it and we'll fix it without opening a hole.
- Removing `dry_run=True` as the default, or any path that submits without the human approval step.
- Automating LinkedIn applications, or captcha solving.
- Raising the 25/day ceiling.

## Adding an ATS adapter

1. Read [src/ats/base.py](src/ats/base.py) and [src/ats/greenhouse.py](src/ats/greenhouse.py).
2. Add `src/ats/<name>.py` using the helpers in [src/ats/common.py](src/ats/common.py). `fill()` must never click Submit; set `submit_selectors` instead.
3. In [src/ats/detector.py](src/ats/detector.py): add the hostname to `_ats_for()`, the name to `_TIER1`, and the class to `adapter_for()`.
4. Add detection tests in `tests/test_ats_adapters.py`.
5. Dry-run against a live posting and mention the URL in the PR.

## Style

- `make lint` (ruff) and `make typecheck` (mypy).
- Type hints on public functions; one module docstring per file; comments explain *why*.

## Commit messages

Imperative first line, at most 72 characters; the body explains why.

## Code of Conduct

Be kind, be specific, assume good faith. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
