# apply-agent dev commands. Run from inside WSL2 Ubuntu.

PY := python3
VENV := .venv
PYBIN := $(VENV)/bin/python

.PHONY: help wizard install dev-install run ping test lint typecheck \
        migrate keygen encrypt-profile passwords secrets-check clean

help:
	@echo "apply-agent — common commands:"
	@echo "  make wizard          interactive setup (run this first)"
	@echo "  make install         create .venv and install runtime deps"
	@echo "  make dev-install     install + dev deps (pytest, ruff, mypy)"
	@echo "  make run             python -m src.main (polling mode)"
	@echo "  make ping            python -m src.main --ping (requires TELEGRAM_*)"
	@echo "  make test            pytest"
	@echo "  make lint            ruff check"
	@echo "  make typecheck       mypy src"
	@echo "  make migrate         alembic upgrade head"
	@echo "  make keygen          generate secrets/master.age.key (run ONCE; back it up)"
	@echo "  make encrypt-profile read secrets/profile.yaml, encrypt to .age, delete plaintext"
	@echo "  make passwords       echo path to secrets/portal_passwords.csv"
	@echo "  make secrets-check   grep for committed secrets (age/API/token shapes)"
	@echo "  make clean           remove caches; leaves secrets/ and *.db untouched"

$(VENV):
	$(PY) -m venv $(VENV)

install: $(VENV)
	$(PYBIN) -m pip install --upgrade pip
	$(PYBIN) -m pip install -e .

dev-install: $(VENV)
	$(PYBIN) -m pip install --upgrade pip
	$(PYBIN) -m pip install -e ".[dev]"

wizard:
	$(PYBIN) -m scripts.setup_wizard

run:
	$(PYBIN) -m src.main

ping:
	$(PYBIN) -m src.main --ping

test:
	$(PYBIN) -m pytest

lint:
	$(PYBIN) -m ruff check src tests scripts

typecheck:
	$(PYBIN) -m mypy src

migrate:
	$(PYBIN) -m alembic upgrade head

keygen:
	@test ! -f secrets/master.age.key || (echo "REFUSE: secrets/master.age.key exists. Move it aside first." && exit 1)
	age-keygen -o secrets/master.age.key
	@echo ""
	@echo "BACK UP secrets/master.age.key NOW. Lose this file = lose every portal password."

encrypt-profile:
	$(PYBIN) -m scripts.encrypt_profile

passwords:
	@echo "Portal passwords mirror: $$(pwd)/secrets/portal_passwords.csv"

secrets-check:
	@echo "Scanning for committed secrets (should print nothing)..."
	@# Universal credential shapes: age private key, Google API key, Telegram
	@# bot token. These name no person — just secret formats this tool handles.
	@# secrets/ is gitignored (never committed) but holds your real keys locally,
	@# so exclude it — we only care whether a secret would be committed.
	@! grep -rEn \
		--exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules \
		--exclude-dir=__pycache__ --exclude-dir=.ruff_cache --exclude-dir=.pytest_cache \
		--exclude-dir=secrets \
		'(AGE-SECRET-KEY-1[0-9A-Z]{20,}|AIza[0-9A-Za-z_-]{35}|[0-9]{8,10}:[A-Za-z0-9_-]{35})' . \
		|| (echo "FAIL: secret-shaped string found above" && exit 1)
	@echo "OK: no committed secrets."

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
