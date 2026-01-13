# app/services/__init__.py
# Лише реекспортуємо те, що потрібно зовні; для шаблонів використовуємо DAL.
from app.DAL.post_templates_operations import list_templates_full, get_template_by_id

__all__ = ["list_templates_full", "get_template_by_id"]
