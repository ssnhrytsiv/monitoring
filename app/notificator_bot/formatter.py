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


def format_admin_message(
    project: str,
    admin: str,
    items: List[str],
    total_views: int | None = None,
    post_title: str | None = None,
    group_id: int | None = None,
    first_item_number: int = 1,
    post_publish_date_text: str | None = None,
    views_capture_date_time_text: str | None = None,
) -> str:
    """
    Формує текст повідомлення для одного адміна всередині проекту.
    """
    lines: List[str] = [f"<b>Проект:</b> {project}", f"<b>Админ:</b> {admin}"]
    if group_id is not None:
        lines.append(f"<b>ID:</b> {group_id}")
    if post_title:
        lines.append(f"<b>Пост:</b> {post_title}")
    for item_number, line in enumerate(items, max(1, int(first_item_number))):
        lines.append(f"{item_number}) {line}")

    has_date_footer = bool(post_publish_date_text or views_capture_date_time_text)
    if has_date_footer:
        lines.append("")
    if total_views is not None:
        total_fmt = f"{total_views:,}".replace(",", " ")
    else:
        total_fmt = "—"
    if post_publish_date_text:
        lines.append(f"<i>Дата выхода поста: {post_publish_date_text}</i>")
    if views_capture_date_time_text:
        lines.append(f"<i>Дата и время снятия просмотров: {views_capture_date_time_text}</i>")
    lines.append(f"Суммарные просмотры: {total_fmt}")
    return "\n".join(lines)
