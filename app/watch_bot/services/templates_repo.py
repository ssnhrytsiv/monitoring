# app/watch_bot/services/templates_repo.py
from typing import Dict, Any
import logging

from app.DAL.post_templates_operations import list_templates_full_db
from app.DAL import session_scope

log = logging.getLogger("templates_repo")


def load_templates_map() -> Dict[int, Dict[str, Any]]:
    """
    Повертає dict {template_id: {"title": str|None, "links_json": str|None}}.
    Використовує DAL list_templates_full і не звертається до полів через індекси.
    """
    try:
        with session_scope() as db:
            rows = list_templates_full_db(db)
    except Exception as e:
        log.exception("load_templates_map failed: %s", e)
        return {}

    templates: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            templates[int(row.id)] = {
                "title": row.title,
                "links_json": row.links,
            }
        except Exception:
            continue
    return templates
