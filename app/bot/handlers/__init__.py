from aiogram import Router

from app.bot.handlers.create_watch import router as create_watch_router
from app.bot.handlers.active_watches_menu import router as active_watches_menu_router
from app.bot.handlers.active_watches_group import router as active_watches_group_router
from app.bot.handlers.join_channels import router as join_channels_router
from app.bot.handlers.pagination import router as pagination_router

router = Router()
router.include_router(create_watch_router)
router.include_router(active_watches_menu_router)
router.include_router(active_watches_group_router)
router.include_router(join_channels_router)
router.include_router(pagination_router)
