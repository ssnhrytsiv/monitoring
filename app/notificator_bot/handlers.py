from __future__ import annotations

from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent


async def inline_handler(inline_query: InlineQuery):
    query = inline_query.query.strip()
    if not query:
        title = "Статусы вотчей"
        message = "Скоро тут будуть швидкі команди для статусів."
    else:
        title = f"Запит: {query}"
        message = f"Ви надіслали: {query}\n(інлайн-режим тестовий)"

    result = InlineQueryResultArticle(
        id="status_1",
        title=title,
        input_message_content=InputTextMessageContent(message_text=message),
        description="Тестова відповідь нотіфікатора",
    )
    await inline_query.answer([result], cache_time=1, is_personal=True)
