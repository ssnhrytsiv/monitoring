from aiogram import Router

from app.admin_bot.bot.handlers.admins import router as admins_router

router = Router()
router.include_router(admins_router)
