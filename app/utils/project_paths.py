from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


def normalize_sqlite_url(raw_url: str | None, *, default_path: str | Path) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return f"sqlite:///{resolve_project_path(default_path)}"

    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value

    sqlite_path = value[len(prefix):]
    if sqlite_path == ":memory:":
        return value

    return f"sqlite:///{resolve_project_path(sqlite_path)}"
