# apply-agent dev commands. Run from Linux, macOS or WSL2 (not PowerShell).

PY := python3
VENV := .venv
PYBIN := $(VENV)/bin/python
# CPU-only torch: the local embedding model is tiny, and the CUDA build is
# several GB. Remove TORCH_INDEX to use your platform's default torch.
TORCH_INDEX := --index-url https://download.pytorch.org/whl/cpu

.PHONY: help setup wizard install dev-install browsers run ping doctor scan test lint \
        typecheck check migrate keygen encrypt-profile edit-profile passwords secrets-check backup clean

help:
	@echo "apply-agent — common commands:"
	@echo "  make setup           install everything + guided setup (start here)"
	@echo "  make doctor          check your setup and say what's missing"
	@echo "  make run             start the daemon (Telegram bot + inbox + scheduler), dry-run"
	@echo "  make scan            scan watchlist.yaml for new matching roles"
	@echo "  make ping            send a Telegram ping (needs TELEGRAM_*)"
	@echo "  make install         create .venv and install runtime deps"
	@echo "  make dev-install     install + dev deps (pytest, ruff, mypy)"
	@echo "  make browsers        install Playwright's Chromium"
	@echo "  make migrate         create / upgrade the database"
	@echo "  make keygen          generate secrets/master.age.key (run ONCE; back it up)"
	@echo "  make encrypt-profile validate + encrypt secrets/profile.yaml, delete plaintext"
	@echo "  make edit-profile    decrypt the profile back to secrets/profile.yaml to edit"
	@echo "  make check           lint + typecheck + tests (what CI runs)"
	@echo "  make backup          snapshot secrets/, data/ and the DB (scripts/backup.sh)"
	@echo "  make passwords       print where the password CSV mirror lives"
	@echo "  make secrets-check   grep for committed secrets (age/API/token shapes)"
	@echo "  make clean           remove caches; leaves secrets/ and *.db untouched"

$(VENV):
	$(PY) -m venv $(VENV)
	$(PYBIN) -m pip install --upgrade pip

install: $(VENV)
	$(PYBIN) -m pip install $(TORCH_INDEX) torch
	$(PYBIN) -m pip install -e .

dev-install: $(VENV)
	$(PYBIN) -m pip install $(TORCH_INDEX) torch
	$(PYBIN) -m pip install -e ".[dev]"

browsers:
	$(PYBIN) -m playwright install --with-deps chromium || $(PYBIN) -m playwright install chromium

setup: install browsers
	@mkdir -p secrets data
	$(PYBIN) -m scripts.setup_wizard
	$(PYBIN) -m src.main --doctor --offline || true

wizard:
	@test -x $(PYBIN) || (echo "Run 'make install' (or 'make setup') first." && exit 1)
	@mkdir -p secrets data
	$(PYBIN) -m scripts.setup_wizard

run:
	$(PYBIN) -m src.main

ping:
	$(PYBIN) -m src.main --ping

doctor:
	$(PYBIN) -m src.main --doctor

scan:
	$(PYBIN) -m src.main --scan

test:
	$(PYBIN) -m pytest

lint:
	$(PYBIN) -m ruff check src tests scripts

typecheck:
	$(PYBIN) -m mypy src

check: lint typecheck test

migrate:
	$(PYBIN) -m alembic upgrade head

keygen:
	@mkdir -p secrets && chmod 700 secrets
	@test ! -f secrets/master.age.key || (echo "REFUSE: secrets/master.age.key exists. Move it aside first." && exit 1)
	age-keygen -o secrets/master.age.key
	@chmod 600 secrets/master.age.key
	@echo ""
	@echo "BACK UP secrets/master.age.key NOW. Lose this file = lose every portal password."

encrypt-profile:
	$(PYBIN) -m scripts.encrypt_profile

edit-profile:
	$(PYBIN) -m scripts.encrypt_profile --decrypt

passwords:
	@echo "Portal passwords mirror: $$(pwd)/secrets/portal_passwords.csv"

backup:
	bash scripts/backup.sh

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
