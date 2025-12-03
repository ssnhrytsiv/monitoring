from typing import Optional, Any, Dict, List, Tuple
import re

GroupItem = Tuple[int, int, str, str, int]
SingleWatch = Tuple[
    int,
    Optional[int],
    str,
    Optional[str],
    Any,
    Optional[int],
    Optional[str],
]

MDV2_SPECIALS = r"_*[]()~`>#+-=|{}.!\\"


def escape_mdv2(text: str) -> str:
    if not text:
        return ""
    return re.sub(
        f"([{re.escape(MDV2_SPECIALS)}])",
        r"\\\1",
        text,
    )


def fmt_tw_end_human(s: Optional[str]) -> str:
    if not s:
        return "—"
    return str(s)


def short_title(title: Optional[Any], tid: Optional[int]) -> str:
    if title is None:
        return f"tpl#{tid}" if tid else "—"
    t = str(title).strip()
    if not t:
        return f"tpl#{tid}" if tid else "—"
    return t.split()[0]


def status_to_emoji(status_s_raw: str) -> str:
    s = (status_s_raw or "").strip()
    if s == "pending":
        return "⏳"
    if s == "matched":
        return "✔️"
    if s == "done":
        return "✅"
    if s == "expired":
        return "🚫"
    if s == "cancelled":
        return "❌"
    return "❔"


def build_group_table(
    all_items: List[GroupItem],
    templates_map: Dict[int, Dict[str, Any]],
    channel_titles: Dict[int, str],
    owner_display: str,
) -> str:
    ID_W = 6
    TITLE_W = 10
    CHAN_W = 14
    STATUS_W = 2

    lines: List[str] = []
    lines.append(owner_display)

    header_line = (
        f"{'ID':<{ID_W}} "
        f"{'Title':<{TITLE_W}} "
        f"{'Назва каналу':<{CHAN_W}} "
        f"{'St':<{STATUS_W}}"
    )
    lines.append(header_line)

    for wid_i, cid_i, status_s_raw, source_url, tpl_id_i in all_items:
        emoji = status_to_emoji(status_s_raw)

        tpl_info: Dict[str, Any] = templates_map.get(tpl_id_i) or {}
        title = tpl_info.get("title") or (f"tpl#{tpl_id_i}" if tpl_id_i else "—")
        title_s = short_title(title, tpl_id_i)

        channel_name = channel_titles.get(cid_i, "—")

        id_col = f"{wid_i:<{ID_W}}"
        title_col = f"{title_s[:TITLE_W]:<{TITLE_W}}"
        chan_col = f"{str(channel_name)[:CHAN_W]:<{CHAN_W}}"
        chan_col = f"{str(channel_name)[:CHAN_W]:<{CHAN_W}}"
        status_col = f"{emoji:<{STATUS_W}}"

        lines.append(f"{id_col} {title_col} {chan_col} {status_col}")

    return "```" + "\n".join(lines) + "```"


def format_single_watch(
    watch: SingleWatch,
    templates_map: Dict[int, Dict[str, Any]],
    channel_titles: Dict[int, str],
    owner_display: str | None = None,
) -> str:
    """
    Формує текст для екрану редагування одного watch'а.
    Зараз використовується в plain-text повідомленні (без parse_mode),
    тому лінк не треба екранувати.
    """
    wid, template_id, status, time_window_end, created_by, channel_id, source_url = (
        watch
    )

    tpl_id = int(template_id) if template_id is not None else None
    tpl_info = templates_map.get(tpl_id or 0) or {}
    raw_title = tpl_info.get("title") or (f"tpl#{tpl_id}" if tpl_id else "—")
    raw_chan_title = channel_titles.get(int(channel_id) if channel_id else 0, "—")
    raw_status = status or ""
    raw_tw_txt = fmt_tw_end_human(
        str(time_window_end)[:16] if time_window_end is not None else None
    )
    raw_owner = owner_display or raw_chan_title or "—"
    raw_source = source_url or ""

    # ці поля ми можемо легенько екранувати (на випадок, якщо колись знову ввімкнемо MarkdownV2),
    # але це не обов'язково для plain text
    title = escape_mdv2(raw_title)
    chan_title = escape_mdv2(raw_chan_title)
    status_text = escape_mdv2(raw_status)
    tw_txt = escape_mdv2(raw_tw_txt)
    owner = escape_mdv2(raw_owner)

    status_emoji = status_to_emoji(status or "")

    lines: List[str] = []
    lines.append(f"Watch #{wid} для {owner}")
    lines.append("")
    lines.append(f"Пост : {title}")
    lines.append(f"Канал   : {chan_title}")
    lines.append(f"Статус  : {status_emoji}")
    lines.append(f"Вікно до: {tw_txt}")
    if raw_source:
        # !!! важливо: тут БЕЗ escape, сирий URL
        lines.append(f"Посилання  : {raw_source}")

    return "\n".join(lines)