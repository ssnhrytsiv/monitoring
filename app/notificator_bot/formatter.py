from __future__ import annotations

from typing import Dict, List


def format_message(project: str, grouped: Dict[str, List[str]]) -> str:
    """
    Формує текст повідомлення (HTML) для одного проекту.
    grouped: admin -> list of lines
    """
    lines: List[str] = [f"<b>Проект:</b> {project}"]
    for admin, items in grouped.items():
        lines.append(f"\n<b>Админ:</b> {admin}")
        for idx, line in enumerate(items, 1):
            lines.append(f"{idx}) {line}")
    return "\n".join(lines)


def format_admin_message(project: str, admin: str, items: List[str], total_views: int | None = None) -> str:
    """
    Формує текст повідомлення для одного адміна всередині проекту.
    """
    lines: List[str] = [f"<b>Проект:</b> {project}", f"<b>Админ:</b> {admin}"]
    for idx, line in enumerate(items, 1):
        lines.append(f"{idx}) {line}")
    if total_views is not None:
        total_fmt = f"{total_views:,}".replace(",", " ")
    else:
        total_fmt = "—"
    lines.append(f"Суммарные просмотры: {total_fmt}")
    return "\n".join(lines)
