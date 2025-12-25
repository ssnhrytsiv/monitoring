from aiogram import Router

from admin_bot.bot.handlers import router as root_router
from admin_bot.bot.report_nav import router as report_router
from admin_bot.bot.admins_menu import router as admins_router

router = Router()
router.include_router(root_router)
router.include_router(report_router)
router.include_router(admins_router)
