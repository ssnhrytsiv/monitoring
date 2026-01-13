"""
Швидка перевірка блоку рендеру звіту у subscription_worker без запуску підписок.
Запуск: python scripts/check_subscription_render.py
"""

from app.admin_bot.services.subscription.subscription_status import render_html_with_statuses
from app.admin_bot.services.report import build_full_footer
from app.admin_bot.services.subscription.subscription_menu import split_text_for_telegram


def demo_success():
    raw_text = "Demo raw text\nSecond line"
    raw_html = None  # підкинь html_text, якщо треба перевірити анкорі
    original_urls = [
        "https://t.me/+demo1",
        "https://t.me/+demo2",
        "https://t.me/+demo3",
    ]
    result_items = [
        {"url": original_urls[0], "status": "already[tg_session_1]", "title": "Канал 1", "channel_id": 111},
        {"url": original_urls[1], "status": "owner_conflict(existing=Владислав)", "title": "Канал 2", "channel_id": 222},
        {"url": original_urls[2], "status": "invalid", "title": "Канал 3", "channel_id": 333},
    ]

    html_report = render_html_with_statuses(result_items, original_urls)
    pages = split_text_for_telegram(html_report, max_len=3500)
    print("=== SUCCESS PATH ===")
    for i, p in enumerate(pages, 1):
        print(f"\n-- page {i} --\n{p}")


def demo_fallback():
    raw_text = "Demo fallback raw text"
    result_items = None  # спеціально зламаємо, щоб потрапити у except
    print("\n=== FALLBACK PATH ===")
    try:
        render_html_with_statuses(None, raw_text, result_items)  # type: ignore[arg-type]
    except Exception:
        footer, sections = build_full_footer([], raw_lines=[raw_text])
        pages = []
        pages.extend(split_text_for_telegram(footer, max_len=3500))
        for label, text in sections:
            pages.extend(split_text_for_telegram(f"{label}:\n{text}", max_len=3500))
        for i, p in enumerate(pages, 1):
            print(f"\n-- fallback page {i} --\n{p}")


if __name__ == "__main__":
    demo_success()
    demo_fallback()
