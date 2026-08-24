"""Interactive setup wizard. Walks a new user from zero to ready.

Usage:
    python -m scripts.setup_wizard

What it does:
    1. Verifies system deps (libreoffice, age, playwright).
    2. Creates .env from .env.example if missing, prompts for the bare-minimum keys.
    3. Generates secrets/master.age.key if missing.
    4. Creates secrets/profile.yaml from profile.example.yaml if missing,
       reminds the user to fill it in and run `make encrypt-profile`.
    5. Runs `alembic upgrade head`.
    6. Reports the path to the password CSV mirror.

Idempotent — safe to re-run.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def info(msg: str) -> None:
    print(f"  \033[36m∙\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"  \033[33m!\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}", file=sys.stderr)


def step(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def check_system_deps() -> None:
    step("1. System dependencies")
    for cmd, hint in [
        ("age", "sudo apt install age"),
        ("libreoffice", "sudo apt install libreoffice --no-install-recommends"),
    ]:
        if shutil.which(cmd):
            ok(f"{cmd} found")
        else:
            warn(f"{cmd} not found — install with: {hint}")


def setup_env() -> None:
    step("2. .env file")
    env = ROOT / ".env"
    example = ROOT / ".env.example"
    if env.exists():
        ok(".env already exists, leaving it alone")
        return
    if not example.exists():
        fail(".env.example missing — clone seems incomplete")
        return
    env.write_text(example.read_text())
    ok(f"Created {env} from .env.example")
    info("Open it and fill in GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.")


def setup_master_key() -> None:
    step("3. Master encryption key")
    key = ROOT / "secrets" / "master.age.key"
    key.parent.mkdir(parents=True, exist_ok=True)
    if key.exists():
        ok("secrets/master.age.key already exists, leaving it alone")
        return
    age = shutil.which("age-keygen")
    if not age:
        fail("age-keygen not in PATH — install age first")
        return
    subprocess.run([age, "-o", str(key)], check=True)
    with contextlib.suppress(PermissionError, OSError):
        key.chmod(0o600)
    ok(f"Created {key}")
    warn(
        "BACK THIS FILE UP NOW (1Password, USB, etc). Losing it = losing every "
        "portal password the vault ever stores.",
    )


def setup_profile() -> None:
    step("4. Profile template")
    profile = ROOT / "secrets" / "profile.yaml"
    enc = ROOT / "secrets" / "profile.yaml.age"
    example = ROOT / "profile.example.yaml"
    if enc.exists():
        ok("Encrypted profile already exists, skipping")
        return
    if profile.exists():
        info(f"{profile} exists (plaintext) — fill in your details, then run `make encrypt-profile`")
        return
    if not example.exists():
        fail("profile.example.yaml missing")
        return
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(example.read_text())
    ok(f"Created {profile} from profile.example.yaml")
    info("Edit it with your real details, then run `make encrypt-profile`.")


def setup_resumes() -> None:
    step("5. Resume directory")
    resumes = ROOT / "resumes"
    resumes.mkdir(parents=True, exist_ok=True)
    master = resumes / "master"
    if any(master.glob("*.md")) if master.exists() else False:
        ok("resumes/master has at least one .md file")
        return
    info("No resume .md files found under resumes/master/.")
    info(f"Drop your resume into {master}/Resume_v1.md to get started.")


def run_migrations() -> None:
    step("6. Database migrations")
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True, cwd=ROOT,
        )
        ok("alembic upgrade head succeeded")
    except subprocess.CalledProcessError:
        fail("alembic failed — run `make migrate` manually to see the error")


def final_summary() -> None:
    step("Done.")
    print(dedent("""
        Next steps:
          1. Edit secrets/profile.yaml with your details.
          2. Run `make encrypt-profile`.
          3. Add real resumes to resumes/<variant>/Resume_v1.md.
          4. Run `make run` to start the agent in polling mode.
          5. From Telegram: /apply <some-greenhouse-url>

        First-time tips:
          • Keep --dry-run on for the first few applications. Review each PDF.
          • Only switch to --no-dry-run after you trust the output.
          • See docs/QUICKSTART.md for the full walkthrough.
    """).rstrip())


def main() -> int:
    print("\n\033[1mapply-agent setup wizard\033[0m\n")
    check_system_deps()
    setup_env()
    setup_master_key()
    setup_profile()
    setup_resumes()
    run_migrations()
    final_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
