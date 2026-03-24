from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.notificator_bot import handlers as notificator_handlers
from app.watch_bot.handlers import create_watch


def test_resolve_template_payload_for_group_prefers_monitoring_media(monkeypatch) -> None:
    monkeypatch.setattr(
        notificator_handlers.watch_posts_db,
        "fetch_watches_by_group",
        lambda group_id: [{"id": 101, "title": "Legacy title"}],
    )
    monkeypatch.setattr(
        notificator_handlers.watch_posts_db,
        "get_watch_info",
        lambda watch_id: {
            "template_id": 555,
            "title": "Legacy title",
            "expected_text_hash": "<b>Expected</b>",
        },
    )
    monkeypatch.setattr(
        notificator_handlers.watch_post_templates_db,
        "get_template_by_id",
        lambda template_id: (
            555,
            "<b>Monitoring text</b>",
            "exact",
            1.0,
            1711111111,
            "Monitoring title",
            None,
            'v2media:{"type":"photo","ids":{},"vault":{"chat_id":-100123,"message_id":777}}',
        ),
    )

    def _unexpected_legacy_lookup(*args, **kwargs):
        raise AssertionError("legacy testing template lookup should not be used when monitoring media exists")

    monkeypatch.setattr(notificator_handlers, "_fetch_testing_template_by_title", _unexpected_legacy_lookup)
    monkeypatch.setattr(notificator_handlers, "_fetch_testing_template_by_text", _unexpected_legacy_lookup)

    payload = notificator_handlers._resolve_template_payload_for_group(9001)

    assert payload is not None
    assert payload["source"] == "monitoring_post_template"
    assert payload["title"] == "Monitoring title"
    assert payload["text"] == "<b>Monitoring text</b>"
    assert payload["media_type"] is None
    assert payload["media_id"] is None
    assert payload["vault_chat_id"] == -100123
    assert payload["vault_message_id"] == 777


def test_build_template_media_payload_from_source_uses_vault_copy(monkeypatch) -> None:
    class FakeBot:
        async def copy_message(self, *, chat_id, from_chat_id, message_id, disable_notification):
            assert chat_id == -100777
            assert from_chat_id == -100555
            assert message_id == 44
            assert disable_notification is True
            return SimpleNamespace(message_id=321)

    monkeypatch.setattr(create_watch, "TEMPLATE_MEDIA_VAULT_CHAT_ID", -100777)

    source_message = SimpleNamespace(
        photo=[SimpleNamespace(file_id="photo-file-id")],
        video=None,
        animation=None,
        chat=SimpleNamespace(id=-100555),
        message_id=44,
        bot=FakeBot(),
    )

    payload = asyncio.run(create_watch._build_template_media_payload_from_source(source_message))

    assert payload == 'v2media:{"type":"photo","ids":{},"vault":{"chat_id":-100777,"message_id":321}}'
