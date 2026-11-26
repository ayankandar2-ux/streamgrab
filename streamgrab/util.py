"""Small shared helpers: sizing, naming, duration parsing, logging."""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from typing import Optional


def human_size(n: Optional[int]) -> str:
    if n is None:
        return "?"
    if n < 1024:
        return f"{n} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(n)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def human_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 180, default: str = "download") -> str:
    """Turn an arbitrary title into a safe cross-platform file name stem."""
    if not name:
        return default
    name = unicodedata.normalize("NFKC", name)
    name = _ILLEGAL.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    # Windows reserved device names
    if name.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = "_" + name
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    return name or default


def parse_iso8601_duration(text: Optional[str]) -> Optional[float]:
    """Parse an ISO-8601 duration such as ``PT1H2M3.5S`` into seconds."""
    if not text:
        return None
    m = re.match(
        r"^P(?:(?P<d>\d+(?:\.\d+)?)D)?"
        r"(?:T(?:(?P<h>\d+(?:\.\d+)?)H)?"
        r"(?:(?P<m>\d+(?:\.\d+)?)M)?"
        r"(?:(?P<s>\d+(?:\.\d+)?)S)?)?$",
        text.strip(),
    )
    if not m:
        return None
    d = float(m.group("d") or 0)
    h = float(m.group("h") or 0)
    mi = float(m.group("m") or 0)
    s = float(m.group("s") or 0)
    return d * 86400 + h * 3600 + mi * 60 + s


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


class Log:
    """Tiny stderr logger with levels, no external deps."""

    LEVELS = {"quiet": 0, "error": 1, "warn": 2, "info": 3, "debug": 4}

    def __init__(self, level: str = "info") -> None:
        self.level = self.LEVELS.get(level, 3)

    def _emit(self, tag: str, msg: str) -> None:
        sys.stderr.write(f"[{tag}] {msg}\n")
        sys.stderr.flush()

    def error(self, msg: str) -> None:
        if self.level >= 1:
            self._emit("error", msg)

    def warn(self, msg: str) -> None:
        if self.level >= 2:
            self._emit("warn", msg)

    def info(self, msg: str) -> None:
        if self.level >= 3:
            self._emit("info", msg)

    def debug(self, msg: str) -> None:
        if self.level >= 4:
            self._emit("debug", msg)


def coerce_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
