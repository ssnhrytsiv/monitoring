from typing import List, Tuple, Callable

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

# (wid, channel_id, status, source_url, template_id)
GroupItem = Tuple[int, int, str, str, int]

PAGE_SIZE = 8


def paginate_items(
    all_items: List[GroupItem],
    page: int,
    page_size: int = PAGE_SIZE,
) -> Tuple[List[GroupItem], int, int]:
    """
    Повертає (page_items, actual_page, total_pages) для all_items.
    """
    total = len(all_items)
    total_pages = max((total + page_size - 1) // page_size, 1)

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    end = start + page_size
    return all_items[start:end], page, total_pages


def build_group_keyboard(
    page_items: List[GroupItem],
    leader_wid: int,
    page: int,
    total_pages: int,
    status_to_emoji: Callable[[str], str],
    get_title_for_tpl: Callable[[int], str],
) -> InlineKeyboardBuilder:
    """
    Будує InlineKeyboardBuilder для поточної сторінки групи:
      [id] [Title] [🔗/—] [status-emoji] [✏] [❌]
      + навігація Prev/Page/Next
    """
    kb = InlineKeyboardBuilder()

    for wid_i, cid_i, status_s_raw, source_link, tpl_id_i in page_items:
        status_emoji = status_to_emoji(status_s_raw)
        title_s = get_title_for_tpl(tpl_id_i)

        kb.button(text=str(wid_i), callback_data="watch:noop")
        kb.button(text=title_s, callback_data="watch:noop")
        if source_link:
            kb.button(text="🔗", url=source_link)
        else:
            kb.button(text="—", callback_data="watch:noop")
        kb.button(text=status_emoji, callback_data="watch:noop")
        kb.button(text="✏", callback_data=f"watch:edit:{wid_i}")
        kb.button(text="❌", callback_data=f"watch:cancel_one:{wid_i}")

    kb.adjust(6)

    # навігація
    nav_row = []

    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=f"watch:group:{leader_wid}:{page-1}",
            )
        )
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="watch:noop"))

    nav_row.append(
        InlineKeyboardButton(
            text=f"Page {page}/{total_pages}",
            callback_data="watch:noop",
        )
    )

    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Next ➡️",
                callback_data=f"watch:group:{leader_wid}:{page+1}",
            )
        )
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="watch:noop"))

    kb.row(*nav_row)

    return kb