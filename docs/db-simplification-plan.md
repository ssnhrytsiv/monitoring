# План: Спрощення схеми БД (URL/Invite кеші)

Цей документ — покроковий план, щоб зменшити дублювання таблиць і зробити один “правильний” шлях fast‑path перед підпискою (subscription worker), без зміни бізнес‑поведінки для користувача.

## Контекст (що є зараз)

Поточна схема має дублювання/розмиті ролі:
- URL → channel_id: `links` + `channel_links`.
- Invite кеш: `invite_cache` (раніше `invite_map` + `invite_status` + частково `url_cache`).
- Статус підписки по каналу/сесії: `membership` (це ок, але треба індекси/унікальність/PK).
- Боти: `bot_links` (окрема сутність, не канал).

## Цільовий стан (to‑be)

1) **Єдина таблиця для URL каналів**
- Таблиця `links` розширена полем `url_norm` (нормалізований ключ).
- UNIQUE(`url_norm`), індекс `channel_id`.
- `channel_links` видалена після міграції.

2) **Єдиний кеш інвайтів**
- Нова таблиця `invite_cache` (або еквівалент) замість `invite_map` + `invite_status`.
- `invite_cache` містить: `invite_hash` (UNIQUE), `channel_id` (FK, nullable), `title` (nullable), `status`, `session`, `updated_at`, `last_error`.
- `invite_map` і `invite_status` видалені після міграції.

3) **`url_cache`**
- Або дропнути (рекомендовано), або залишити лише як fallback (потрібно підтвердити роль).

4) **`membership`**
- UNIQUE(`channel_id`, `account`), індекс `channel_id`, FK на `channels`.

5) **Боти**
- `t.me/<username_bot>` зберігаємо тільки в `bot_links` і не змішуємо з каналами.

## Принципи реалізації

- Alembic — єдине джерело правди для схеми.
- Вся робота з БД лише в `app/DAL/**`.
- Бізнес‑логіка не будує запитів (лише викликає DAL).
- Міграції робимо без “дропу” старих таблиць до моменту, поки нова схема не запрацює в проді.

## Де зараз використовується стара схема (що саме переписувати)

Цей список потрібен, щоб не “загубити” використання старих таблиць під час міграції. Для кожного пункту вказано, на який етап(и) плану він переїжджає.

### `channel_links` (мапінг нормалізованого URL -> channel_id)

**Де використовується**
- `app/services/joiner.py` — `map_invite_set/get`, статуси, усе в `invite_cache`.
- `app/services/requested_reconciler.py` — запис мапінгу інвайту в `invite_cache`.
- `app/admin_bot/services/subscription/subscription_worker.py` — fast‑path через `invite_cache`.
- `app/admin_bot/services/subscription/refresh_channels_subscription.py` — fallback читає `invite_cache`.
- `app/admin_bot/services/networks.py` — будує інвайт через `invite_cache`.
- `app/admin_bot/services/admins.py` — cleanup: бере інвайти з `invite_cache`.
- `app/watch_bot/services/channels_repo.py` — fallback через `invite_cache`.
- SQL/інтеграції: `channels_table.sql` — JOIN через `invite_cache`.
- Скрипти: refresh/cleanup/compare — на `invite_cache`.

**Заміна на нову логіку**
- `invite_cache` єдиним джерелом `invite_hash -> channel_id/title/status`, legacy `invite_map`/`invite_status` дропнуті (Alembic 20260305_120000).

### `invite_status` (invite_hash -> статус/ts)

Повністю видалено: дані перенесені у `invite_cache.status/updated_at/session/last_error`, legacy таблиця дропнута (Alembic 20260305_120000), виклики `invite_status_*` замінені на `invite_cache_status_*`.

### `url_cache` (URL -> статус/ts)

**Де використовується**
- `app/db/models.py` — модель `UrlCache`. (Етап 4/6)
- `app/DAL/membership_operations.py` — `url_get()/url_put()` + селекти/чистки по множині URL. (Етап 4)
- `app/admin_bot/services/subscription/subscription_worker.py` — fast‑path: якщо `url_cache` має фінальний статус або duplicate — не робимо мережу. (Етап 4)
- `app/admin_bot/services/admins.py` — pre‑count і delete з `url_cache` (зараз ще є прямий SQL‑DELETE у сервісі). (Етап 4)
- `app/admin_bot/services/subscription/refresh_channels_subscription.py` — звіти/статистика, очистка `url_cache`. (Етап 4)
- `app/services/joiner.py` — після join/already пише `url_put(cleaned_url, ...)` (тобто поповнює `url_cache`). (Етап 4)
- Скрипти:
  - `scripts/sync_url_cache_links.py`, `scripts/seed_evgeniy_links.py` (обслуговування `url_cache`). (Етап 4)

**Заміна на нову логіку**
- Етап 4 (варіант A або B):
  - A: прибрати `url_cache` повністю: fast‑path робити через `links.url_norm` + `invite_cache` + `membership` (по `channel_id` + account/session).
  - B: звузити роль `url_cache` до fallback‑кейсів (потрібно чітке визначення, які URL не покриваються `links.url_norm`/`invite_cache`).
- Після міграції: видалити/оновити всі скрипти, що синхронізують `url_cache`.

### `subscriptions` (вже дропнута)

**Де ще залишились згадки**
- Скрипти `scripts/cleanup_broken_limit_channels.py`, `scripts/cleanup_specific_invites.py` (DELETE з `subscriptions`).
- `docs/db-schema.md` (описує `subscriptions` як частину блоку сабскрипшенів).

**Що зробити**
- Прибрати/оновити згадки в скриптах/доках (не повинно використовуватись у runtime).

## План робіт

### Етап 0 — Підготовка

- [ ] Зробити бекап прод‑БД (файл SQLite) перед будь‑якими міграціями.
- [ ] Зафіксувати поточні метрики:
  - кількість рядків у `links`, `channel_links`, `invite_map`, `invite_status`, `url_cache`, `membership`.
  - частку “дублів” URL у `links` (один raw_url → багато рядків).
- [ ] Додати/оновити тести там, де вони потрібні для нових DAL функцій (особливо нормалізація URL та кеш інвайтів).

### Етап 1 — Нормалізований URL ключ у `links`

**Схема**
- [x] Alembic: додати колонку `links.url_norm` (TEXT, nullable на першому кроці).
- [x] Alembic: створити індекс `links.url_norm` (тимчасово без UNIQUE).
- [x] Alembic: створити UNIQUE індекс на `links.url_norm` (після backfill/чистки).
- [x] Alembic: додати індекс `links.channel_id` (якщо ще немає).

**Backfill**
- [ ] DAL: додати функцію, яка повертає `url_norm` для будь‑якого URL каналу (public/invite/joinchat).
- [x] Скрипт/міграція: заповнити `links.url_norm` для всіх існуючих рядків.
  - [x] Виявити конфлікти (два різні raw_url → один url_norm): видаляємо дублікати, лишаємо найстаріший `links.id` перед увімкненням UNIQUE.
- [x] Після backfill: включити UNIQUE(`url_norm`) в `links`.

- **Код**
- [ ] DAL (`app/DAL/channels_operations.py`):
  - [x] `add_link(...)` → завжди записує `url_norm`.
  - [x] `find_channel_by_link(...)` → шукає по `url_norm` (а не по `raw_url`).
  - [x] `get_channel_id_by_url(...)` → нормалізує URL і шукає по `links.url_norm`.
- [x] Бізнес‑логіка: замінити пошук через `channel_links` на DAL `get_channel_id_by_url`.
  - [x] `app/watch_bot/services/channels_repo.py` (прибрано прямий `SessionLocal`, використовує DAL)

**Тимчасова сумісність**
- [ ] На перехідний період (1 реліз): read‑fallback:
  - якщо `links.url_norm` ще не заповнений/не знайдено — fallback на старі механізми (після повного rollout прибрати).

### Етап 2 — Відмова від `channel_links`

- [x] Перевірити, де використовується `channel_links` (код + SQL‑шаблони).
- [x] Перенести логіку, що залежить від `channel_links`, на `links.url_norm`.
  - [x] `app/watch_bot/services/channels_repo.py`
  - [x] `app/services/googlesheets/channels_table.sql`
  - [x] Скрипти cleanup: `scripts/cleanup_broken_limit_channels.py`, `scripts/cleanup_specific_invites.py`
- [x] Alembic: дропнути таблицю `channel_links`.
- [x] Оновити документацію `docs/db-schema.md`.

### Етап 3 — `invite_cache` (об’єднання `invite_map` + `invite_status`) — виконано

**Схема**
- [x] Alembic: створити таблицю `invite_cache`.
  - UNIQUE(`invite_hash`)
  - INDEX(`channel_id`)
  - `updated_at` (INTEGER або TEXT, узгодити з існуючим стилем часу)

**Backfill**
- [x] Заповнити `invite_cache` з `invite_map` + `invite_status`:
  - join по `invite_hash`
  - status брати з `invite_status`, title/channel_id з `invite_map`

**Код**
- [ ] DAL (`app/DAL/membership_operations.py` або окремий `app/DAL/invite_cache_operations.py`):
  - [x] `map_invite_set/get` та `invite_status_*` тепер пишуть/читають `invite_cache` (зворотна сумісність із `invite_map`/`invite_status` залишається тимчасово).
  - [x] Виділити окремі `get_invite_cache` / `upsert_invite_cache` та прибрати дублювання через `invite_map`/`invite_status`.
- [x] `app/services/joiner.py`:
  - [x] всі записи `map_invite_set/invite_status_set` перевести на `invite_cache`.
- [x] `subscription_worker`:
  - [x] fast‑path по invite_hash робити через `invite_cache`.
- [x] Оновити місця, які читають `invite_map` напряму:
  - `app/admin_bot/services/subscription/refresh_channels_subscription.py` (fallback при видаленні/звітності)
  - `app/admin_bot/services/networks.py` (побудова t.me/+hash)
  - `app/services/googlesheets/channels_table.sql` (CTE invites -> invite_cache)
  - Скрипти `scripts/refresh_channel_titles_from_tg.py` та `scripts/cleanup_*`

### Етап 4 — `url_cache`: або прибрати, або звузити роль

Варіант A (рекомендовано): прибрати
- [ ] Замінити використання `url_cache` на комбінацію:
  - `links.url_norm` → `channel_id`
  - `invite_cache` (для інвайтів)
  - `membership` (final status)
- [ ] Alembic: дропнути `url_cache`.

Варіант B: лишити fallback
- [ ] Чітко визначити, які URL не покриваються `links.url_norm` / `invite_cache`.
- [ ] Оставити `url_cache` лише для цих випадків (і перестати писати туди “канальні” URL).

### Етап 5 — `membership` (унікальність/індекси/FK)

- [ ] Alembic: UNIQUE(`channel_id`,`account`) (якщо ще не в схемі), INDEX(`channel_id`).
- [ ] Alembic: FK `membership.channel_id -> channels.channel_id` (для SQLite: увімкнути foreign_keys і протестувати міграцію на копії).
- [ ] DAL: гарантувати UPSERT для membership (не множити рядки).

### Етап 6 — Прибирання старих таблиць

- [x] Alembic: дропнути `invite_map` і `invite_status` (20260305_120000_drop_invite_map_status).
- [ ] Якщо обрано варіант A: дропнути `url_cache`.
- [x] Alembic: дропнути `invite_attempts` (не використовувалась).
- [ ] Прибрати з коду всі fallback‑гілки, які тримали старі таблиці.

### Етап 7 — Верифікація

- [ ] Юніт‑тести: покрити:
  - нормалізацію URL → `url_norm`
  - fast‑path “already” без мережі
  - invite_cache: backfill і читання/запис
- [ ] Інтеграційно (локально): прогнати підписку на:
  - `t.me/+hash`
  - `t.me/username`
  - `t.me/username_bot` (має піти в `bot_links` і “skip”)
- [ ] Перевірити, що повторний запуск з тими самими URL іде по fast‑path (без `ensure_join`).

### Етап 8 — Прод‑роллаути

- [ ] Реліз 1: додати нові поля/таблиці + dual‑write/read‑fallback.
- [ ] Перевірити логи/fast‑path на проді 24–48 год.
- [ ] Реліз 2: прибрати старі таблиці + прибрати fallback‑гілки.

## Критерії готовності

- Повторне додавання вже обробленого URL:
  - не викликає мережевий `ensure_join`,
  - одразу дає статус `already/duplicate` в репорті.
- В БД немає дублювання URL між `links`/`channel_links` (бо `channel_links` видалена).
- Invite статуси й мапінги не дублюються між `invite_map`/`invite_status`/`url_cache` (бо є `invite_cache`).

## Rollback стратегія

- До дропу старих таблиць rollback = просто повернути код на попередні читання (fallback‑гілка).
- Після дропу rollback = відкат міграції + відновлення БД з бекапу.
