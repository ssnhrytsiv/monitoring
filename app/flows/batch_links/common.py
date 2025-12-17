import logging
import os
log = logging.getLogger("flow.batch_links.common")

def display_name(slot) -> str:
    try:
        client = getattr(slot, "client", slot)
        # Перевага: збережене людське ім'я акаунта (first/last/username)
        for attr in ("human_display", "_human_display"):
            v = getattr(slot, attr, None) or getattr(client, attr, None)
            if v:
                return str(v)
        fn = getattr(getattr(client, "session", None), "filename", None)
        if fn:
            try:
                base = os.path.basename(str(fn))
                root, _ = os.path.splitext(base)
                return root or base
            except Exception:
                return str(fn)
    except Exception:
        pass
    for attr in ("name", "label", "session_name"):
        if hasattr(slot, attr):
            try:
                v = getattr(slot, attr)
                if v:
                    return str(v)
            except Exception:
                pass
    return "slot"
