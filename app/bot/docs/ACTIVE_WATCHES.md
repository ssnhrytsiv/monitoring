# Active watches – структура і де що шукати

Цей файл документує логіку **активних вотчів**: список груп, деталізація групи, канали, скасування.

## Задіяні файли

- `handlers/active_watches_menu.py`
- `handlers/active_watches_group.py`
- `services/active_watches_service.py`
- `services/watches_repo.py`
- `services/channels_repo.py`
- `services/templates_repo.py`
- `utils/active_watches_formatters.py`
- `utils/active_watches_pagination.py`

---

## Реєстрація router’ів

```python
from aiogram import Router

from app.bot.handlers.create_watch import router as create_watch_router
from app.bot.handlers.active_watches_menu import router as active_watches_menu_router
from app.bot.handlers.active_watches_group import router as active_watches_group_router
from app.bot.handlers.join_channels import router as join_channels_router

router = Router()
router.include_router(create_watch_router)
router.include_router(active_watches_menu_router)
router.include_router(active_watches_group_router)
router.include_router(join_channels_router)
```

---

## 1. handlers/active_watches_menu.py

**Призначення:** показати список груп вотчів користувача з вибором типу статусу.

### Основний хендлер

```python
@router.callback_query(F.data.startswith("menu:list_active"))
async def menu_list_active(cb: CallbackQuery):
    ...
```

Логіка:

1. Якщо статус не передано, показує меню вибору з трьох кнопок:
   - `Активні` (`pending`);
   - `Відслідковуються перегляди` (`matched`);
   - `Вийшли з терміну` (`expired`).
2. `rows = list_active_watches(cb.from_user.id, statuses=...)` – бере сирі вотчі користувача відповідного статусу.
3. `groups = group_active(rows)` – групує їх за (template_id, time_window_end, created_by).
4. Для кожної групи:
   - обирає `leader_wid` (максимальний id у групі);
   - рахує кількість каналів;
   - визначає owner’ів каналів (`get_owners_by_channel_ids`);
   - бере коротку назву шаблону (`_short_title`).

Формує текст:

```text
№ | Template | Channels | Owner | Window

<leader_wid> | <title_short> | <chans_n> | <owner_txt> | до <tw_txt>
```

Кнопки на рядок:

- `[leader_wid]` — `callback_data="watch:noop"` (просто id).
- `[owner_txt]` — `callback_data="watch:group:<leader_wid>:<status_key>"` (перейти в деталі групи з тим самим фільтром).
- `[❌ Cancel]` — `callback_data="watch:cancel:<leader_wid>:<status_key>"` (скасувати групу, залишаючись у тому ж фільтрі).

Допоміжні функції:

- `_short_title(title, tid)` — перше слово або `tpl#<id>`.
- `_fmt_tw_end(s)` — форматування `Window` (рядок дати/часу).

---

## 2. handlers/active_watches_group.py

**Призначення:** детальна робота з однією групою вотчів: таблиця, пагінація, канали, скасування.

### Хендлери

#### 2.1. watch_noop

```python
@router.callback_query(F.data == "watch:noop")
async def watch_noop(cb: CallbackQuery):
    await cb.answer()
```

Порожній callback для «неактивних» кнопок (щоб Telegram не показував помилку).

#### 2.2. watch_channels

```python
@router.callback_query(F.data.startswith("watch:channels:"))
async def watch_channels(cb: CallbackQuery):
    ...
```

- Парсить `leader_wid`.
- Викликає `load_group_channels(leader_wid)` (service) → список `channel_id`.
- Через `get_links_by_channel_ids(cids)` дістає URL’и каналів.
- Повертає їх одним alert’ом через `cb.answer(txt, show_alert=True)`.

#### 2.3. watch_cancel

```python
@router.callback_query(F.data.startswith("watch:cancel:"))
async def watch_cancel(cb: CallbackQuery):
    ...
```

- Парсить `leader_wid`.
- Викликає `cancel_group_watches(leader_wid)` (service), який:
  - оновлює всі `watch_posts` у групі на `status='cancelled'`;
  - пише `watch_event`.
- Відповідає:
  - при успіху: `cb.answer("Скасовано")`;
  - при помилці: `cb.answer("Не зміг скасувати", show_alert=True)`.
- Для оновлення списку:
  - імпортує `menu_list_active` з `active_watches_menu.py`;
  - викликає `await menu_list_active(cb)`.

#### 2.4. watch_group_details

```python
@router.callback_query(F.data.startswith("watch:group:"))
async def watch_group_details(cb: CallbackQuery):
    ...
```

Головний хендлер деталізації групи.

1. Розбирає `leader_wid`, `status_key` та `page` з `cb.data`:
   - `watch:group:<leader_wid>:<status_key>`
   - `watch:group:<leader_wid>:<status_key>:<page>`
   (`status_key` може бути відсутнім, тоді дефолт pending+matched)

2. Отримує ключ групи:

   ```python
   tid_i, tw_key, cby, leader_cid = get_group_leader_key(leader_wid)
   ```

3. Завантажує всі елементи групи:

   ```python
   all_items = load_group_items(tid_i, tw_key, cby, statuses=STATUS_PRESETS.get(status_key))
   # all_items: List[(wid, channel_id, status, source_url, template_id)]
   ```

4. Пагінація для кнопок:

   ```python
   page_items, page, total_pages = paginate_items(all_items, page, PAGE_SIZE)
   ```

5. Підготовка довідкових мап:

   ```python
   templates_map = load_templates_map()
   cids = [cid for _, cid, _, _, _ in all_items if cid]

   channel_names_map = get_titles_by_channel_ids(cids) or {}
   owners_map        = get_owners_by_channel_ids(cids) or {}
   ```

6. Визначає `owner_for_header` — перший owner з групи, fallback — назва каналу чи "—".

7. Будує текст таблиці:

   ```python
   table_block = build_group_table(
       all_items,
       templates_map=templates_map,
       channel_titles=channel_names_map,
       owner_display=owner_for_header,
   )
   ```

8. Будує клавіатуру для поточної сторінки:

   ```python
   kb = build_group_keyboard(
       page_items=page_items,
       leader_wid=leader_wid,
       page=page,
       total_pages=total_pages,
       status_to_emoji=status_to_emoji,
       get_title_for_tpl=lambda tpl_id: short_title(
           templates_map.get(tpl_id, {}).get("title"),
           tpl_id,
       ),
       status_key=status_key,
   )
   kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu:list_active"))
   ```

9. Формує заголовок:

   ```python
   tw_txt = fmt_tw_end_human(tw_key)
   header = f"Вотч для {owner_for_header}, час вікна до {tw_txt} — вотч активний і працює"
   text = header + "\n\n" + table_block
   ```

10. Редагує або надсилає повідомлення з цим текстом + клавіатурою.

---

## 3. services/active_watches_service.py

**Призначення:** бізнес‑логіка для активних вотчів поверх таблиці `watch_posts`.

### Типи

```python
GroupItem = Tuple[int, int, str, str, int]
# (wid, channel_id, status, source_url, template_id)
```

### Функції

1. `get_group_leader_key(leader_wid) -> (template_id, tw_key, created_by, channel_id) | None`

   - Читає:

     ```sql
     SELECT template_id, time_window_end, created_by, channel_id
     FROM watch_posts
     WHERE id = ?
     ```

   - Повертає:
     - `template_id` як `int | None`;
     - `tw_key` — `time_window_end` обрізаний до хвилини (`YYYY-MM-DD HH:MM`);
     - `created_by`;
     - `channel_id` лідера (як `int | None`).

2. `load_group_items(template_id, tw_key, created_by) -> List[GroupItem]`

   - Вибирає:

     ```sql
     SELECT id, template_id, status, time_window_end, created_by, channel_id, source_url
     FROM watch_posts
     WHERE status IN ('pending','matched')
       AND template_id IS ?
       AND (created_by IS ? OR created_by IS NULL)
     ORDER BY id DESC
     ```

   - Усередині ще раз фільтрує по `tw_key` (до хвилини).
   - Повертає список `(wid, channel_id, status, source_url, template_id)`.

3. `load_group_channels(leader_wid) -> List[int]`

   - По `leader_wid` бере `(template_id, time_window_end, created_by)`.
   - Вибирає:

     ```sql
     SELECT id, channel_id
     FROM watch_posts
     WHERE template_id IS ?
       AND time_window_end IS ?
       AND created_by IS ?
       AND status IN ('pending','matched')
     ```

   - Повертає список `channel_id` для групи.

4. `cancel_group_watches(leader_wid) -> bool`

   - По `leader_wid` бере `(template_id, time_window_end, created_by)`.
   - Робить:

     ```sql
     UPDATE watch_posts
     SET status='cancelled', updated_at=?
     WHERE template_id IS ?
       AND time_window_end IS ?
       AND created_by IS ?
       AND status IN ('pending','matched','expired')
     ```

   - Коммітить, додає `insert_watch_event(leader_wid, "cancelled", {...})`.
   - Повертає `True` при успіху, `False`, якщо лідер не знайдений або сталася помилка.

---

## 4. utils/active_watches_formatters.py

**Призначення:** форматування даних для виводу (час, статуси, текст таблиці).

### Типи

```python
GroupItem = Tuple[int, int, str, str, int]
```

### Функції

- `fmt_tw_end_human(tw_key: Optional[str]) -> str`  
  Повертає людиночитний текст часу вікна (зараз — просто рядок або "—").

- `short_title(title, tid) -> str`  
  Перше слово з title або `tpl#<id>`.

- `status_to_emoji(status: str) -> str`  
  Мапінг статусів:
  - `pending` → ⏳
  - `matched` → ✔️
  - `done` → ✅
  - `expired` → 🚫 (зараз не показуємо в списку, але мапінг лишається)
  - `cancelled` → ❌
  - інше → ❔

- `build_group_table(all_items, templates_map, channel_titles, owner_display) -> str`  
  Будує моноширинну таблицю з усіма елементами групи й повертає готовий Markdown‑code‑block.

---

## 5. utils/active_watches_pagination.py

**Призначення:** пагінація списку `all_items` і побудова клавіатури сторінок.

### Константа

```python
PAGE_SIZE = 8
```

### Функції

- `paginate_items(all_items, page, page_size=PAGE_SIZE) -> (page_items, actual_page, total_pages)`  
  Рахує `total_pages`, коригує `page` в діапазоні `[1, total_pages]`, повертає шматочок `all_items[start:end]`.

- `build_group_keyboard(page_items, leader_wid, page, total_pages, status_to_emoji, get_title_for_tpl) -> InlineKeyboardBuilder`  
  Створює кнопки:
  - рядки по `[id] [Title] [🔗/—] [status-emoji] [✏] [❌]`;
  - нижній рядок навігації `⬅️ Prev | Page X/Y | Next ➡️`.

---

## Швидка шпаргалка: де що міняти

- **Змінити формат / вигляд таблиці, емодзі, тексти**  
  → `utils/active_watches_formatters.py`

- **Змінити розмір сторінки, логіку пагінації, навігаційні кнопки**  
  → `utils/active_watches_pagination.py`

- **Змінити фільтрацію/SQL/які записи входять до групи**  
  → `services/active_watches_service.py`

- **Змінити поведінку при переході в групу, скасуванні, перегляді каналів**  
  → `handlers/active_watches_group.py`

- **Змінити список груп/меню активних вотчів**  
  → `handlers/active_watches_menu.py`
