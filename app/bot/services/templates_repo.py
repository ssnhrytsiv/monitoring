# app/bot/services/templates_repo.py
from typing import Dict, Any, Optional
import logging

log = logging.getLogger("templates_repo")

def load_templates_map() -> Dict[int, Dict[str, Any]]:
    try:
        from app.services import post_watch_db as pdb
        fn = getattr(pdb, "list_templates_full", None)
        if not fn:
            return {}
        rows = fn()
        mp: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            try:
                tid = int(r[0])
                title = r[5] if len(r) > 5 else None
                links_json = r[6] if len(r) > 6 else None
                mp[tid] = {"title": title, "links_json": links_json}
            except Exception:
                continue
        return mp
    except Exception as e:
        log.exception(f"load_templates_map failed: {e}")
        return {}