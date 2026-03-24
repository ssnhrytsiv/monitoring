# app/watch_bot/services/templates_repo.py
from typing import Dict, Any, Optional
import logging

from app.DAL.post_templates_operations import list_templates_full

log = logging.getLogger("templates_repo")


def load_templates_map() -> Dict[int, Dict[str, Any]]:
    """
    Повертає dict {template_id: {"title": str|None, "links_json": str|None}}.
    Використовує DAL list_templates_full і не звертається до полів через індекси.
    """
    try:
        rows = list_templates_full()
    except Exception as e:
        log.exception("load_templates_map failed: %s", e)
        return {}

    templates: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            (
                template_id,
                _text,
                _mode,
                _threshold,
                _created_at,
                title,
                links_json,
                _photo_id,
            ) = row
            templates[int(template_id)] = {
                "title": title,
                "links_json": links_json,
            }
        except Exception:
            continue
    return templates
