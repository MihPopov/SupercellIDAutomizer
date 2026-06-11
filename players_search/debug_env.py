from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from players_search.env_loader import load_dotenv_file


def _mask(value: Optional[str]) -> str:
    if not value:
        return "<empty>"
    v = value.strip()
    if len(v) <= 10:
        return v
    return f"{v[:6]}…{v[-4:]}"


def debug_env() -> None:
    cwd = Path.cwd()
    env_path = cwd / ".env"
    print(f"CWD: {cwd}")
    print(f".env exists: {env_path.exists()} ({env_path})")

    load_dotenv_file()

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    ocr_engine = os.getenv("OCR_ENGINE")

    print(f"SUPABASE_URL: {_mask(url)}")
    if url:
        print(f"  raw prefix: {url.strip()[:32]}")
    print(f"SUPABASE_SERVICE_ROLE_KEY: {_mask(key)}")
    print(f"OCR_ENGINE: {ocr_engine or 'tesseract'}")
    if key:
        print(f"  key startswith 'eyJ': {key.strip().startswith('eyJ')}")

