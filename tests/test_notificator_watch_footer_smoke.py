from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.notificator_bot import handlers as notificator_handlers
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


def test_build_line_for_views_access_lost_prompts_to_update_link() -> None:
    line = notificator_service._build_line(
        "views_access_lost",
        {
            "matched_session": "tg_session_11",
            "reason_code": "views_access_lost",
        },
        {
            "matched_session": "tg_session_11",
            "updated_at": "2026-03-22 23:11:00",
        },
        "Test Channel",
        "https://t.me/test_channel",
        "2026-03-22 23:11:00",
    )

    assert "Не удалось снять просмотры" in line
    assert "tg_session_11" in line
    assert "обновите ссылку" in line


def test_build_line_for_views_retry_scheduled_shows_technical_problem_and_retry_time() -> None:
    line = notificator_service._build_line(
        "views_retry_scheduled",
        {
            "session_used": "tg_session_11",
            "error_type": "TimeoutError",
            "error_message": "temporary network failure",
            "next_retry_at": "2026-03-23 00:14:00",
            "reason_code": "views_retry_scheduled",
        },
        {
            "matched_session": "tg_session_11",
            "updated_at": "2026-03-23 00:10:00",
        },
        "Test Channel",
        "https://t.me/test_channel",
        "2026-03-23 00:10:00",
    )

    assert "Не удалось снять просмотры сейчас" in line
    assert "TimeoutError" in line
    assert "tg_session_11" in line
    assert "2026-03-23 00:14:00" in line


def test_build_line_for_views_access_lost_uses_human_session_label(monkeypatch) -> None:
    monkeypatch.setattr(
        notificator_service,
        "session_display",
        lambda raw_session_name: "Taga Zaiyrov" if raw_session_name == "tg_session_6" else raw_session_name,
    )

    line = notificator_service._build_line(
        "views_access_lost",
        {
            "matched_session": "tg_session_6",
            "reason_code": "views_access_lost",
        },
        {
            "matched_session": "tg_session_6",
            "updated_at": "2026-03-22 23:11:00",
        },
        "Test Channel",
        "https://t.me/test_channel",
        "2026-03-22 23:11:00",
    )

    assert "Taga Zaiyrov" in line
    assert "tg_session_6" not in line


def test_build_line_for_views_access_lost_message_not_found_is_not_reported_as_access_loss(monkeypatch) -> None:
    monkeypatch.setattr(
        notificator_service,
        "session_display",
        lambda raw_session_name: "Тимур Риферт" if raw_session_name == "tg_session_7" else raw_session_name,
    )

    line = notificator_service._build_line(
        "views_access_lost",
        {
            "matched_session": "tg_session_7",
            "status": "message_not_found",
            "reason_code": "views_access_lost",
        },
        {
            "matched_session": "tg_session_7",
            "updated_at": "2026-03-24 20:49:40",
        },
        "Football House ~ Футбол",
        "https://t.me/test_channel",
        "2026-03-24 20:49:40",
    )

    assert "Сообщение уже недоступно" in line
    assert "потеряла доступ" not in line
    assert "Тимур Риферт" in line


def test_build_line_for_views_access_lost_old_catchup_is_reported_clearly() -> None:
    line = notificator_service._build_line(
        "views_access_lost",
        {
            "status": "matched_too_old",
            "reason_code": "views_access_lost",
        },
        {
            "updated_at": "2026-03-24 20:49:40",
        },
        "Test Channel",
        "https://t.me/test_channel",
        "2026-03-24 20:49:40",
    )

    assert "слишком старый для catch-up" in line


def test_build_line_for_views_retry_scheduled_uses_human_session_label(monkeypatch) -> None:
    monkeypatch.setattr(
        notificator_service,
        "session_display",
        lambda raw_session_name: "M M" if raw_session_name == "tg_session_4" else raw_session_name,
    )

    line = notificator_service._build_line(
        "views_retry_scheduled",
        {
            "session_used": "tg_session_4",
            "error_type": "TimeoutError",
            "error_message": "temporary network failure",
            "next_retry_at": "2026-03-23 00:14:00",
            "reason_code": "views_retry_scheduled",
        },
        {
            "matched_session": "tg_session_4",
            "updated_at": "2026-03-23 00:10:00",
        },
        "Test Channel",
        "https://t.me/test_channel",
        "2026-03-23 00:10:00",
    )

    assert "M M" in line
    assert "tg_session_4" not in line
    assert "2026-03-23 00:14:00" in line


def test_build_line_for_reply_watch_uses_reply_specific_matched_text() -> None:
    line = notificator_service._build_line(
        "matched",
        {
            "is_reply": True,
        },
        {
            "is_reply": True,
            "matched_at": "2026-03-23 10:00:00",
        },
        "Reply Channel",
        "https://t.me/reply_channel",
        "2026-03-23 10:00:00",
    )

    assert "Ответка опубликована" in line


def test_build_line_for_reply_watch_uses_reply_specific_deleted_text() -> None:
    line = notificator_service._build_line(
        "deleted",
        {
            "is_reply": True,
        },
        {
            "is_reply": True,
            "deleted_at": "2026-03-23 11:00:00",
        },
        "Reply Channel",
        "https://t.me/reply_channel",
        "2026-03-23 11:00:00",
    )

    assert "Ответка удалена" in line


def test_resolve_group_row_line_time_text_prefers_deleted_at_for_deleted() -> None:
    group_row = {
        "deleted_at": "2026-03-23 11:00:00",
        "updated_at": "2026-03-23 11:00:05",
    }

    deleted_time_text = notificator_service._resolve_group_row_line_time_text("deleted", group_row)

    assert deleted_time_text == "2026-03-23 11:00:00"


def test_notification_pages_no_longer_append_visible_page_footer() -> None:
    notification_page_texts = notificator_service._build_notification_pages_with_visible_index(
        project="PROJECT",
        admin="Admin",
        lines=["x" * 5000],
        total_views=100,
        post_title="Title",
        group_id=354,
        post_publish_date_text="12.03.2026",
        views_capture_date_time_text="18:45, 12.03.2026",
        message_max_length=260,
    )

    assert len(notification_page_texts) >= 1
    assert all("Сторінка " not in notification_page_text for notification_page_text in notification_page_texts)


def test_notification_navigation_markup_shows_page_index_as_noop_button() -> None:
    markup = notificator_handlers.build_notification_navigation_markup("session-1", 0, 2)

    assert markup is not None
    first_row = markup.inline_keyboard[0]
    assert [button.text for button in first_row] == ["1/2", "Вперед ➡️"]
    assert first_row[0].callback_data == notificator_handlers.NOTIFICATION_PAGE_NOOP_CALLBACK_DATA


def test_collect_grouped_events_keeps_human_session_name_for_group_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        notificator_service,
        "fetch_unsent_events",
        lambda limit=1000: [
            (
                501,
                1001,
                "views_access_lost",
                '{"status":"access_lost","matched_session":"tg_session_7"}',
                "2026-03-24 20:49:40",
            )
        ],
    )
    monkeypatch.setattr(
        notificator_service,
        "_get_watch_info",
        lambda watch_id: {
            "channel_id": 1666747423,
            "project": "PROJECT",
            "group_id": 9001,
            "matched_session": "tg_session_7",
            "source_url": "https://t.me/test_channel",
            "updated_at": "2026-03-24 20:49:40",
            "title": "Football House ~ Футбол",
        },
    )
    monkeypatch.setattr(
        notificator_service.watch_posts_db,
        "fetch_watches_by_group",
        lambda group_id: [
            {
                "id": 1001,
                "channel_id": 1666747423,
                "source_url": "https://t.me/test_channel",
                "status": "views_access_lost",
                "updated_at": "2026-03-24 20:49:40",
                "created_at": "2026-03-24 20:40:00",
                "matched_at": "2026-03-24 20:41:00",
                "coverage_check_at": "2026-03-24 20:49:40",
                "deleted_at": "",
                "final_views": None,
                "title": "Football House ~ Футбол",
                "is_reply": False,
                "matched_session": "tg_session_7",
            }
        ],
    )
    monkeypatch.setattr(notificator_service, "_fetch_channel", lambda channel_id: {"id": channel_id})
    monkeypatch.setattr(
        notificator_service,
        "_channel_meta",
        lambda channel_id, fallback_url: ("Football House ~ Футбол", "https://t.me/test_channel"),
    )
    monkeypatch.setattr(notificator_service, "_admin_name", lambda chan_info, watch_info: "Admin")
    monkeypatch.setattr(
        notificator_service,
        "session_display",
        lambda raw_session_name: "Тимур Риферт" if raw_session_name == "tg_session_7" else raw_session_name,
    )

    grouped, _, _ = notificator_service.collect_grouped_events()

    key = ("PROJECT", "Admin", 9001)
    line = grouped[key][1001]["line"]
    assert "Тимур Риферт" in line
    assert "tg_session_7" not in line


def test_notification_page_navigation_handler_restores_media_pages(monkeypatch) -> None:
    restored = {}

    async def _fake_restore(callback_query, *, notification_page_session_identifier, target_page_number, answer_text=None):
        restored["session"] = notification_page_session_identifier
        restored["page"] = target_page_number

    monkeypatch.setattr(notificator_handlers, "_restore_notification_page", _fake_restore)

    callback_query = SimpleNamespace(
        data="notifpage:session-1:2",
        message=SimpleNamespace(),
        answer=lambda *args, **kwargs: None,
    )

    asyncio.run(notificator_handlers.notification_page_navigation_handler(callback_query))

    assert restored == {"session": "session-1", "page": 2}
