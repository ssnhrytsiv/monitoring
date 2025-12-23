from aiogram import Router

from admin_bot.bot.handlers import router as root_router

router = Router()
router.include_router(root_router)
