from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse


def is_windows_drive_path(value: str) -> bool:
    raw = str(value or "")
    return len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha()


def is_local_path_reference(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    if parsed.scheme in {"", "file"}:
        return True
    return is_windows_drive_path(str(value or ""))


def normalize_local_path_reference(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            raw = f"//{unquote(parsed.netloc)}{raw_path}"
        else:
            raw = raw_path
        if raw.startswith("/") and len(raw) >= 4 and raw[2] == ":" and raw[1].isalpha():
            raw = raw[1:]
        return os.path.expanduser(raw)
    return os.path.expanduser(str(value or ""))


def resolve_local_path(value: str) -> Path:
    return Path(normalize_local_path_reference(value)).resolve()
