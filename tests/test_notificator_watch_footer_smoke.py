from __future__ import annotations

from app.notificator_bot import formatter
from app.notificator_bot import service as notificator_service


def test_format_admin_message_includes_watch_footer_dates() -> None:
    formatted_message = formatter.format_admin_message(
        project="PROJECT",
        admin="Admin",
        items=["https://t.me/test — Опубликован ☑️ (время: 12:00:00)"],
        total_views=1200,
        post_title="Test title",
        group_id=354,
        post_publish_date_text="12.03.2026",
        views_capture_date_time_text="18:45, 12.03.2026",
    )

    assert "<i>Дата выхода поста: 12.03.2026</i>" in formatted_message
    assert "<i>Дата и время снятия просмотров: 18:45, 12.03.2026</i>" in formatted_message


def test_format_admin_message_places_total_views_at_bottom_with_spacing_before_dates() -> None:
    formatted_message = formatter.format_admin_message(
        project="PROJECT",
        admin="Admin",
        items=["https://t.me/test — Опубликован ☑️ (время: 12:00:00)"],
        total_views=1200,
        post_title="Test title",
        group_id=354,
        post_publish_date_text="12.03.2026",
        views_capture_date_time_text="18:45, 12.03.2026",
    )

    formatted_message_lines = formatted_message.splitlines()
    assert formatted_message_lines[-1] == "Суммарные просмотры: 1 200"
    assert "" in formatted_message_lines
    post_line_index = formatted_message_lines.index("1) https://t.me/test — Опубликован ☑️ (время: 12:00:00)")
    date_line_index = formatted_message_lines.index("<i>Дата выхода поста: 12.03.2026</i>")
    assert formatted_message_lines[date_line_index - 1] == ""
    assert date_line_index > post_line_index


def test_notification_pages_keep_watch_footer_dates_when_split() -> None:
    very_long_notification_line = "x" * 5000
    notification_page_texts = notificator_service._build_notification_pages_with_length_limit(
        project="PROJECT",
        admin="Admin",
        lines=[very_long_notification_line],
        total_views=100,
        post_title="Title",
        group_id=354,
        post_publish_date_text="12.03.2026",
        views_capture_date_time_text="18:45, 12.03.2026",
        message_max_length=260,
    )

    assert len(notification_page_texts) >= 1
    for notification_page_text in notification_page_texts:
        assert "<i>Дата выхода поста: 12.03.2026</i>" in notification_page_text
        assert "<i>Дата и время снятия просмотров: 18:45, 12.03.2026</i>" in notification_page_text


def test_extract_notification_footer_datetime_texts_returns_earliest_values() -> None:
    watch_group_entries = [
        {
            "matched_at_datetime_text": "2026-03-12 10:05:00",
            "views_capture_datetime_text": "2026-03-12 19:00:00",
        },
        {
            "matched_at_datetime_text": "2026-03-11 23:55:00",
            "views_capture_datetime_text": "2026-03-12 18:30:00",
        },
        {
            "matched_at_datetime_text": "",
            "views_capture_datetime_text": None,
        },
    ]

    post_publish_date_text, views_capture_date_time_text = notificator_service._extract_notification_footer_datetime_texts(
        watch_group_entries
    )

    assert post_publish_date_text == "11.03.2026"
    assert views_capture_date_time_text == "18:30, 12.03.2026"


def test_resolve_group_row_line_time_text_prefers_coverage_time_for_views() -> None:
    group_row = {
        "coverage_check_at": "2026-03-12 18:30:00",
        "updated_at": "2026-03-12 18:48:00",
        "created_at": "2026-03-12 17:00:00",
    }

    views_time_text = notificator_service._resolve_group_row_line_time_text("views", group_row)
    matched_time_text = notificator_service._resolve_group_row_line_time_text("matched", group_row)

    assert views_time_text == "2026-03-12 18:30:00"
    assert matched_time_text == "2026-03-12 18:48:00"
