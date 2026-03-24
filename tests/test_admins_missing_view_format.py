from __future__ import annotations

import os
import sys


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.admin_bot.bot import admins_menu


def test_missing_channels_view_moves_checked_at_to_single_footer(monkeypatch) -> None:
    missing_channel_record_list = [
        {
            "channel_label": "Вагнер в Telegram",
            "channel_url": "https://t.me/test_one",
            "audit_status": "missing",
            "missing_detected_at": 1742681355,
            "checked_at": 1742681355,
        },
        {
            "channel_label": "Русский Медвежонок",
            "channel_url": "https://t.me/test_two",
            "audit_status": "missing",
            "missing_detected_at": 1742675556,
            "checked_at": 1742681355,
        },
    ]

    monkeypatch.setattr(
        admins_menu.channel_subscription_audit_operations,
        "list_missing_channels_for_admin",
        lambda admin_identifier, page_number, page_size: (
            missing_channel_record_list,
            len(missing_channel_record_list),
        ),
    )

    text, keyboard = admins_menu._build_missing_channels_view(admin_id=7, page_number=0)

    assert "Статус:" not in text
    assert "Missing з:" not in text
    assert text.count("Перевірено:") == 1
    assert (
        f"Перевірено: <code>{admins_menu._format_audit_datetime(1742681355)}</code>"
        in text
    )
    assert "• <a href=\"https://t.me/test_one\">Вагнер в Telegram</a>" in text
    assert "• <a href=\"https://t.me/test_two\">Русский Медвежонок</a>" in text

    keyboard_buttons = [
        button
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert any(
        button.text == "Добавить каналы"
        and button.callback_data == "admin_missing_add_channels:7"
        for button in keyboard_buttons
    )
