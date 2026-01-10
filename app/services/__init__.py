# app/services/__init__.py
from .post_watch_db import list_templates_full, get_template_by_id  # реекспорт API для шаблонів

__all__ = ["list_templates_full", "get_template_by_id"]
