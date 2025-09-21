# app/services/html_match.py
from __future__ import annotations

import re

# Нормалізація «технічного шуму», але збереження HTML-структури/емодзі
_ZW = "[\u200b\u200c\u200d\u200e\u200f]"  # zero-width chars
_RE_WS = re.compile(r"[ \t\r\f\v]+")      # багаторазові пробіли (без \n)

def _norm_html(s: str | None) -> str:
    if not s:
        return ""
    # прибираємо zero-width, уніфікуємо пробіли поза \n, тримаємо теги як є
    s = re.sub(_ZW, "", s)
    s = s.replace("\u00a0", " ")  # NBSP -> звичайний пробіл
    # не чіпаємо \n, щоб не зламати блокову верстку
    s = _RE_WS.sub(" ", s)
    # стрип у краях
    return s.strip()

def exact_html_equal(a: str | None, b: str | None) -> bool:
    """
    «Точне» порівняння по HTML: зберігаємо теги/емодзі/стилі.
    Дозволяємо лише мінімальну нормалізацію службових символів/пробілів.
    """
    return _norm_html(a) == _norm_html(b)