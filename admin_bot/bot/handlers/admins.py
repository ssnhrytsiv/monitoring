from __future__ import annotations

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from admin_bot.db.session import SessionLocal
from admin_bot.services import admins as svc_admins
from admin_bot.config import ADMIN_ALLOWED_IDS

router = Router()


def _db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _is_allowed(user_id: int | None) -> bool:
    if not ADMIN_ALLOWED_IDS:
        return True
    if user_id is None:
        return False
    return user_id in ADMIN_ALLOWED_IDS


@router.message(Command("start"))
async def cmd_start(m: Message):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    await m.answer("Адмін-бот: використовуйте /admins щоб подивитися зареєстрованих адмінів.")


@router.message(Command("admins"))
async def cmd_list_admins(m: Message):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    db = next(_db())
    admins = svc_admins.list_admins(db)
    if not admins:
        await m.answer("Адмінів поки немає.")
        return
    lines = []
    for a in admins:
        disp = a.display or ""
        uname = f"@{a.username}" if a.username else ""
        lines.append(f"{a.id}. {disp} {uname} (tg_id={a.tg_id})")
    await m.answer("\n".join(lines))
