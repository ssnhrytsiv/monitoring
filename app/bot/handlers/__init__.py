from aiogram import Router

from app.bot.handlers.create_watch import router as create_watch_router
from app.bot.handlers.active_watches import router as active_watches_router
from app.bot.handlers.join_channels import router as join_channels_router

router = Router()
router.include_router(create_watch_router)
router.include_router(active_watches_router)
router.include_router(join_channels_router)
