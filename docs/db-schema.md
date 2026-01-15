# DB Schema Map (post_watchdog.sqlite3)

Коротка мапа таблиць і де вони використовуються, щоб уникати дублів і розуміти точки входу.

- **ORM/Base**: спільний `app.admin_bot.db.models.Base` + додаткові моделі в `app/services/models.py` (`InviteCheck`, `RequestedCheck`).  
- **Alembic**: `alembic/env.py` націлений на спільний Base; поточний базовий ревізія `20240229_010101`, baseline `1d271c13555e`.

## Основні таблиці і використання
- `channels`, `links`, `channel_links`: DAO `app/DAL/channels_operations.py`, репозиторії `admin_bot/services/channels.py`; скрипти `cleanup_*`, `leave_unknown_channels.py`, `compare_db_with_sessions.py`.
- `networks`, `network_channels`: `admin_bot/services/networks.py`, DAO `app/DAL/network_channels_operations.py`, хендлери create_watch (відбір проєкту/сітки).
- `sheet_projects`, `sheet_project_archives`: активні Google Sheets по проєктах; DAO `app/DAL/sheet_projects_operations.py`, використання в `app/watch_bot/handlers/create_watch.py`, `gsheets_buffer.py`.
- `post_template`: шаблони постів; DAO `app/DAL/post_templates_operations.py`, плагіни `post_templates`.
- `watch_posts`, `watch_events`, `watch_candidates`, `watch_groups`: логіка вотчів і нотифікацій; використовуються через DAO в `app/DAL/watch_*_operations.py`, моделі у `posts_watch_result_models.py`, хендлери `active_watches_*`, `gsheets_buffer` (запис статусів).
- `bot_links`: посилання на боти; DAO `app/DAL/bot_links_operations.py`, меню адмінів (`admin_bot/bot/admins_menu.py`).
- `invite_map`, `invite_status`, `invite_owners`, `membership`, `membership_status`, `subscriptions`, `url_cache`, `link_queue`: блок сабскрипшенів/інвайтів; DAO в `app/DAL/membership_operations.py`, використовуються у `admins.py`, subscription воркерах, скриптах `upgrade_channel_membership_schema.py`, `cleanup_*`.
- `owner_conflicts`, `owner_actions`: резолюція власників; `app/services/owner_conflict_guard.py`, `admin_bot/services/admins.py`.
- `notifier_state`, `notifier_messages`: стан/історія нотифікатора; `app/notificator_bot/models.py`.

## Поточні дублі/врахування
- Моделі таблиць уже описані в `app/admin_bot/db/models.py`; `app/services/models.py` тепер лише реекспортує їхній Base і додає унікальні таблиці.
- Для нотифікатора використовуємо тільки `app/notificator_bot/db/__init__.py` та `posts_watch_result_models.py`; дубль `app/notificator_bot/db.py` видалено.
- Alembic слід вести від спільного Base, нові зміни схеми робити міграціями; baseline ревізія додана.

## Наступні кроки (DAO/ORM)
1) Узгодити нотифікаторські моделі (`watch_*`, `notifier_*`) у спільному Base або залишити окремим модулем, але підключеним до Alembic.

## Імпорти, що посилаються на `admin_bot.db` (для подальшої заміни/перенесення)
- admin_bot/services/channels.py: `from app.admin_bot.db import models as m`
- admin_bot/services/admins.py: `from app.admin_bot.db import models as m`
- admin_bot/services/owner_conflicts.py: `from app.admin_bot.db import models as m`
- admin_bot/bot/handlers/admins.py: `from app.admin_bot.db.session import SessionLocal`
- admin_bot/run.py: `from app.admin_bot.db.session import Base, engine, migrate_admins_nullable`
- admin_bot/main.py: `from app.admin_bot.db.session import Base, engine`
- admin_bot/services/networks.py: `from app.admin_bot.db import models as m`
- admin_bot/db/models.py: `from app.admin_bot.db.session import Base`
- admin_bot/services/subscription/subscription_worker.py: `from app.admin_bot.db.models import upsert_membership`
- admin_bot/services/subscription/subscription_worker.py: `from app.admin_bot.db.session import SessionLocal`
- admin_bot/services/subscription/subscription_worker.py: `from app.admin_bot.db import models as m`
- alembic/env.py: `from app.admin_bot.db import models as shared_models`
- scripts/compare_db_with_sessions.py: `from app.admin_bot.db.session import SessionLocal`
- scripts/compare_db_with_sessions.py: `from app.admin_bot.db import models as m`
- admin_bot/bot/admins_menu.py: `from app.admin_bot.db import models as m`
- admin_bot/bot/admins_menu.py: `from app.admin_bot.db.session import SessionLocal`
- admin_bot/services/subscription/refresh_channels_subscription.py: `from app.admin_bot.db.session import SessionLocal`
- admin_bot/services/subscription/refresh_channels_subscription.py: `from app.admin_bot.db import models as m`
- app/services/models.py: `from app.admin_bot.db.session import engine as _engine, SessionLocal, Base`
- app/services/models.py: `from app.admin_bot.db import models as admin_models`
- app/watch_bot/handlers/create_watch.py: `from app.admin_bot.db.session import SessionLocal as AdminSession`
- app/watch_bot/handlers/create_watch.py: `from app.admin_bot.db import models as adm_models`
