import logging
log = logging.getLogger("flow.batch_links.common")

def display_name(slot) -> str:
    try:
        client = getattr(slot, "client", slot)
        fn = getattr(getattr(client, "session", None), "filename", None)
        if fn:
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