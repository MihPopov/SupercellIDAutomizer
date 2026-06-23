from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for i, ch in enumerate(value):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "#" and not in_single and not in_double and i > 0 and value[i - 1].isspace():
            return value[:i].rstrip()
    return value.strip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        value = value[1:-1]
        if quote == '"':
            value = value.replace(r"\n", "\n").replace(r"\r", "\r")
    return value


def _load_dotenv_fallback(dotenv_path: Path) -> bool:
    if not dotenv_path.exists():
        return False

    loaded = False
    for raw_line in dotenv_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _unquote(_strip_inline_comment(value)))
        loaded = True
    return loaded


def _dotenv_candidates() -> list[Path]:
    cwd_dotenv = Path.cwd() / ".env"
    repo_dotenv = Path(__file__).resolve().parent.parent / ".env"
    candidates = [cwd_dotenv]
    if repo_dotenv != cwd_dotenv:
        candidates.append(repo_dotenv)
    return candidates


def load_dotenv_file() -> bool:
    """
    Load .env from the current working directory, then from the repo root.

    Uses python-dotenv when it is installed, but falls back to a small parser so
    local UI/debug commands can still start and report useful errors before the
    user installs optional project dependencies.
    """
    loaded = False
    if importlib.util.find_spec("dotenv") is not None:
        dotenv = importlib.import_module("dotenv")
        for dotenv_path in _dotenv_candidates():
            loaded = bool(dotenv.load_dotenv(dotenv_path=dotenv_path)) or loaded
        return loaded
    for dotenv_path in _dotenv_candidates():
        loaded = _load_dotenv_fallback(dotenv_path) or loaded
    return loaded
