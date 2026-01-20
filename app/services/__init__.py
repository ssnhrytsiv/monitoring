# app/services/__init__.py
# Компактні обгортки для сервісів, які все ще імпортуються старою сигнатурою.
from app.DAL import session_scope
from app.DAL import post_templates_operations as tpl_db


def list_templates_full(limit: int = 50):
    """Compat-обгортка: відкриває сесію та повертає DTO з DAL."""
    with session_scope() as db:
        return tpl_db.list_templates_full_db(db, limit=limit)


def get_template_by_id(template_id: int):
    """Compat-обгортка: відкриває сесію та повертає DTO з DAL."""
    with session_scope() as db:
        return tpl_db.get_template_by_id_db(db, template_id)


__all__ = ["list_templates_full", "get_template_by_id"]
