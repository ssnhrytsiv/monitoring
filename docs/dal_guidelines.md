# DAL / ORM Working Notes

Файл, який треба дивитися першим, щоб не дублювати моделі/DAO і не плодити ручний SQL.

## Джерело моделей
- Канонічний Base/engine: `app/admin_bot/db/session.py` + `app/admin_bot/db/models.py`.
- Додаткові унікальні моделі (InviteCheck, RequestedCheck) – `app/services/models.py`, але вони теж сидять на спільному Base.
- Alembic таргетує спільний Base (`alembic/env.py`); актуальні ревізії: `1d271c13555e` (baseline), `2d3b4a2f9d9c` (вирівнювання моделей, no-op).

## Де розміщувати DAO
- Папка `app/DAL/`, файли за схемою `<table>_operations.py` (наприклад, `channels_operations.py`, `sheet_projects_operations.py`).
- Використовуємо `SessionLocal` (із `admin_bot.db.session` реекспортований в `app/DAL/__init__.py`), а не `sqlite3`/локи.

## Додаємо нову таблицю / функціонал
1. Перевірити, чи модель вже описана в `app/admin_bot/db/models.py` або згадана в `docs/db-schema.md`.
2. Якщо нова:
   - Додати модель у `app/admin_bot/db/models.py` (спільний Base).
   - Згенерувати міграцію Alembic (автоген або ручна).
   - Додати DAO-файл у `app/DAL/<table>_operations.py`.
3. Оновити `docs/db-schema.md` короткою згадкою про таблицю/використання.

## Заборони / пам’ятки
- Не використовувати нові `sqlite3.connect` і `_lock` — тільки ORM/SessionLocal.
- Назви інстансів DAO робити за сутністю (наприклад, `membership_db`, `invite_owner_db`), не generic `dao`.
- Відкривати `SessionLocal()` один раз на шар обробки (наприклад, у хендлері/воркері) і на цій сесії викликати функції DAL напряму: `with SessionLocal() as db: ...`. Не відкривати сесію кожним методом і не використовувати `next(get_db())`, щоб не губити close/commit.
- Перед додаванням моделі/DAO: перевір `docs/db-schema.md` і `app/DAL/`, щоб не дублювати.
- Якщо потрібен raw_connection — брати через `SessionLocal().get_bind().raw_connection()`, а не створювати новий engine.

## TODO: міграція з channel_db на DAO
1) Перенести сирі SQLite сервіси в DAL у класовому стилі DAO (сесія в конструкторі, `self.db`):
   - Очищення SessionLocal по плагінах/воркерах: використовувати один `with SessionLocal() as db:` на виклик і передавати db/DAO.
   - Готово/видалено: `app/services/post_watch_db.py`, `app/services/membership_db.py`, `app/services/subscription_check.py`, `app/services/link_queue.py`, `app/services/db/bad_invites.py`, `app/services/requested_reconciler_db.py`.
   - Legacy прибрано: `channel_maps.py`, `channel_facts.py`, `monitor_links.py` (плагін).
  - Видалено стек batch_links (був вимкнений): `app/plugins/batch_links.py`, `app/plugins/owner_set.py`, `app/flows/batch_links/common.py`, `app/flows/batch_links/process_links.py`, `app/flows/batch_links/queue_worker.py`.
  - Видалені legacy Telethon-плагіни: `help_and_ping.py`, `channel_info.py`, `metrics_watch.py`, `needle_reply.py`, `monitor_watch.py`.
2) Всі нові DAO робити як класи: інстанс приймає Session у `__init__`, методи працюють через `self.db`.
   - Іменувати змінні за сутністю, а не generic `row`: напр. у `set_invite_owner` → `invite_owner`.
   - Дозволено залишати функціональні обгортки `module.method(...)`, але вони мають делегувати в клас DAO і НЕ відкривати нову сесію щоразу — сесію інжектимо зовні.
   - Допускається використовувати `@dataclass` для DAO (поле `db: Session`) як цукор для конструкторів без явного `__init__`.
   - Після завершення міграцій прибрати локальні обгортки в коді (наприклад, у `joiner`) і прокидати `db` зверху, викликаючи функції DAL напряму.
3) Оновити/перегенерувати `docs/PROJECT_MAP.md` після видалення `app/services/channel_db.py`.

## Нотатки по звітам/сесіях
- Статуси типу `already/joined` доповнюємо сесією через `get_any_session_for_channel`; якщо статус уже містить `[sess]`, не перетираємо.
- `link_queue` має унікальний `url`; `enqueue` оновлює існуючі рядки замість падіння на `IntegrityError`.
- Якщо не вистачає title/session у звіті — спершу гідрація: `find_channel_by_link`, `map_invite_get`, `get_session_by_channel`.
