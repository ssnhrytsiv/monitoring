from __future__ import annotations

from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from app.planning_bot.models import PlanningButton

router = Router(name="planning_bot")


def build_menu(buttons: list[PlanningButton]) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text=btn.text, callback_data=btn.callback)]
        for btn in buttons
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.inline_query()
async def inline_echo(iq: InlineQuery):
    query_text = (iq.query or "").strip()
    # Якщо користувач ще нічого не ввів — показуємо стартові підказки.
    display = query_text or "..."

    result_plan = InlineQueryResultArticle(
        id="plan",
        title="Створити план дня",
        description="Натисни, щоб вставити шаблон плану",
        input_message_content=InputTextMessageContent(
            message_text=f"План на сьогодні:\n1) {display}\n2) ...\n3) ..."
        ),
    )

    result_echo = InlineQueryResultArticle(
        id="echo",
        title="Відправити як є",
        description=display if query_text else "Надіслати поточний текст",
        input_message_content=InputTextMessageContent(message_text=query_text or ""),
    )

    result_task = InlineQueryResultArticle(
        id="task",
        title="Задача з дедлайном",
        description="Створити задачу DD.MM HH:MM",
        input_message_content=InputTextMessageContent(
            message_text=f"🗓 Задача: {display}\nДедлайн: DD.MM HH:MM"
        ),
    )

    await iq.answer([result_plan, result_task, result_echo], cache_time=0, is_personal=True)
