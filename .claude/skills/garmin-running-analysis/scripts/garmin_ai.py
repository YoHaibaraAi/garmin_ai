#!/usr/bin/env python3
"""Portable launcher and preflight check for the local garmin-ai project."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ENV = "GARMIN_AI_PROJECT_ROOT"
PROJECT_NAME = "garmin-ai"


def _is_project(path: Path) -> bool:
    pyproject = path / "pyproject.toml"
    cli = path / "src" / "garmin_ai" / "cli.py"
    if not pyproject.is_file() or not cli.is_file():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return f'name = "{PROJECT_NAME}"' in text or f"name = '{PROJECT_NAME}'" in text


def _discover_project(explicit: str | None) -> tuple[Path | None, str]:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return (path if _is_project(path) else None, "--project-root")

    configured = os.environ.get(PROJECT_ENV)
    if configured:
        path = Path(configured).expanduser().resolve()
        return (path if _is_project(path) else None, PROJECT_ENV)

    script = Path(__file__).resolve()
    candidates: list[tuple[Path, str]] = []
    for parent in (Path.cwd().resolve(), *Path.cwd().resolve().parents):
        candidates.append((parent, "current-directory"))
    for parent in script.parents:
        candidates.append((parent, "skill-repository"))
    candidates.append((Path.home() / "github.com" / "garmin_ai", "default-location"))

    seen: set[Path] = set()
    for candidate, source in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if _is_project(candidate):
            return candidate, source
    return None, "not-found"


def _parse_args(argv: list[str]) -> tuple[str | None, str | None, list[str]]:
    explicit: str | None = None
    action: str | None = None
    remaining = list(argv)

    while remaining:
        arg = remaining[0]
        if arg == "--":
            remaining.pop(0)
            break
        if arg == "--project-root":
            if len(remaining) < 2:
                raise ValueError("--project-root requires a path")
            explicit = remaining[1]
            del remaining[:2]
            continue
        if arg.startswith("--project-root="):
            explicit = arg.split("=", 1)[1]
            remaining.pop(0)
            continue
        if arg in {"--doctor", "--setup", "--wrapper-help"}:
            action = arg[2:]
            remaining.pop(0)
            continue
        break
    return explicit, action, remaining


def _venv_entrypoint(project: Path | None) -> Path | None:
    if project is None:
        return None
    candidates = [
        project / ".venv" / "bin" / "garmin-ai",
        project / ".venv" / "Scripts" / "garmin-ai.exe",
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _print_wrapper_help() -> None:
    print(
        """Usage:
  garmin_ai.py [--project-root PATH] --doctor
  garmin_ai.py [--project-root PATH] --setup
  garmin_ai.py [--project-root PATH] [--] GARMIN_AI_ARGS...

Environment:
  GARMIN_AI_PROJECT_ROOT  Path to the local garmin-ai repository.

Examples:
  garmin_ai.py --doctor
  garmin_ai.py auth
  garmin_ai.py base --limit 1 --mode basic --json
"""
    )


def _doctor(project: Path | None, source: str) -> int:
    uv = shutil.which("uv")
    entrypoint = _venv_entrypoint(project)
    payload = {
        "ok": bool(project and (entrypoint or uv)),
        "project_root": str(project) if project else None,
        "project_source": source,
        "uv": uv,
        "launcher": str(entrypoint) if entrypoint else ("uv" if uv else None),
        "token_store_present": (Path.home() / ".garminconnect").exists(),
        "config_present": (Path.home() / ".garmin-ai" / "config.json").exists(),
    }
    if not project:
        payload["message"] = (
            f"garmin-ai project not found; pass --project-root or set {PROJECT_ENV}"
        )
    elif not entrypoint and not uv:
        payload["message"] = "neither .venv/bin/garmin-ai nor uv is available"
    else:
        payload["message"] = (
            "preflight passed; token presence does not guarantee that the token is valid"
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def main(argv: list[str]) -> int:
    try:
        explicit, action, cli_args = _parse_args(argv)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if action == "wrapper-help":
        _print_wrapper_help()
        return 0

    project, source = _discover_project(explicit)
    if action == "doctor":
        return _doctor(project, source)
    if project is None:
        print(
            f"garmin-ai project not found ({source}); pass --project-root or set {PROJECT_ENV}",
            file=sys.stderr,
        )
        return 2

    if action == "setup":
        uv = shutil.which("uv")
        if uv is None:
            print("uv is not installed or not on PATH", file=sys.stderr)
            return 2
        if cli_args:
            print("--setup does not accept garmin-ai arguments", file=sys.stderr)
            return 2
        return subprocess.run([uv, "sync"], cwd=project, check=False).returncode

    entrypoint = _venv_entrypoint(project)
    if entrypoint:
        command = [str(entrypoint), *cli_args]
    else:
        uv = shutil.which("uv")
        if uv is None:
            print("run --setup first, or install uv", file=sys.stderr)
            return 2
        command = [uv, "run", "garmin-ai", *cli_args]
    return subprocess.run(command, cwd=project, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
