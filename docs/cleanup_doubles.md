# Документація: інструменти для роботи з membership та дубльованими підписками

Цей файл описує допоміжні скрипти, які ми додали для:

- аналізу таблиці `membership`;
- пошуку дублікатів за різними сесіями (акаунтами);
- експортy дублікатів у JSON;
- очищення БД від дублікатів;
- відписки від каналів у Telegram для зайвих сесій;
- перевірки фактичної кількості каналів по кожній сесії.

## Загальні передумови

- Усі скрипти розраховані на структуру БД `post_watchdog.sqlite3`, де є таблиця:

  ```sql
  CREATE TABLE membership (
    channel_id INTEGER NOT NULL,
    account    TEXT    NOT NULL,
    status     TEXT    NOT NULL, -- joined/already/requested/invalid/private/blocked/too_many
    ts         INTEGER NOT NULL,
    PRIMARY KEY (channel_id, account)
  );
  ```

- У корені проєкту лежать Telegram session-файли:

  - `tg_session.session`
  - `tg_session_2.session`
  - `tg_session_3.session`
  - `tg_session_4.session`

- Primary‑акаунт (той, який лишаємо підписаним на канали) — `tg_session`.

- Для роботи Telethon потрібні змінні середовища:

  ```bash
  export TG_API_ID=...
  export TG_API_HASH=...
  ```

---

## 1. `scripts/list_membership_duplicates.py`

### Призначення

Шукає в таблиці `membership` усі `channel_id`, для яких у системі зареєстровано **більше ніж один `account`**. Тобто показує дублі підписок між різними акаунтами/сесіями.

### Як працює

1. Підключається до БД `post_watchdog.sqlite3`.
2. Виконує запит:

   ```sql
   SELECT channel_id, COUNT(DISTINCT account) AS acc_count
   FROM membership
   GROUP BY channel_id
   HAVING acc_count > 1;
   ```

3. Для кожного знайденого `channel_id` додатково вибирає всі рядки:

   ```sql
   SELECT account, status, ts
   FROM membership
   WHERE channel_id = ?;
   ```

4. Виводить у консоль для кожного каналу:

   - `channel_id`;
   - кількість різних акаунтів;
   - список записів: `account`, `status`, `ts`.

### Використання

```bash
python scripts/list_membership_duplicates.py
```

### Коли корисно

- Перед будь‑якою чисткою, щоб побачити **фактичні дублі** в БД.
- Після чистки — щоб переконатися, що дублікати зникли.

---

## 2. `scripts/export_membership_duplicates.py`

### Призначення

Експортує знайдені дублікати з `membership` у JSON‑файл `membership_duplicates.json`.  
Це “снапшот” стану дублікатів, який використовується пізніше для:

- аналізу;
- синхронної відписки в Telegram;
- повторної перевірки/аудиту.

### Як працює

1. Читає ту саму БД `post_watchdog.sqlite3`.
2. Знаходить усі `channel_id`, для яких є більше ніж один `account` (аналогічно до `list_membership_duplicates.py`).
3. Для кожного такого `channel_id` вибирає:

   ```sql
   SELECT account, status, ts
   FROM membership
   WHERE channel_id = ?;
   ```

4. Формує словник виду:

   ```json
   {
     "2919532453": [
       { "account": "tg_session",   "status": "already", "ts": 1758503519 },
       { "account": "tg_session_2", "status": "already", "ts": 1758503641 },
       { "account": "tg_session_4", "status": "already", "ts": 1758503089 }
     ],
     "1158045480": [
       { "account": "tg_session",   "status": "joined",  "ts": 1764247600 },
       { "account": "tg_session_2", "status": "already", "ts": 1764247810 }
     ]
   }
   ```

5. Записує це в `membership_duplicates.json` у корені проєкту.

### Використання

```bash
python scripts/export_membership_duplicates.py
```

### Коли корисно

- Перед змінами в БД / відписками в Telegram — щоб мати повний список, “з чого саме ми будемо виходити”.
- Як вхідні дані для `cleanup_membership_duplicates_full.py`.

---

## 3. `scripts/cleanup_membership_duplicates_db_only.py`

> Файл створювали під час роботи; якщо його ще немає в репозиторії, логіка описана тут для подальшого додавання.

### Призначення

Привести таблицю `membership` до стану, де для кожного `channel_id` залишився **лише primary‑акаунт** (`tg_session`) у ролі “підписника”. Усі інші `account` для того ж `channel_id` видаляються з таблиці.

Цей скрипт **не торкається Telegram‑підписок**, лише БД.

### Як працює

1. Підключається до `post_watchdog.sqlite3`.
2. Знаходить усі `channel_id` з дублікатами (`COUNT(DISTINCT account) > 1`).
3. Для кожного `channel_id`:

   - отримує список `(account, status, ts)`;
   - якщо серед `account` є `PRIMARY_ACCOUNT = "tg_session"`, тоді:
     - залишає рядок з `account = "tg_session"`;
     - видаляє всі інші `account` для цього `channel_id` з `membership`;
   - якщо `tg_session` для цього `channel_id` **немає**, канал пропускається (для безпеки).

4. Пише в консоль:

   - які канали обробляє;
   - які акаунти залишає/видаляє;
   - скільки рядків видалено.

### Використання

```bash
python scripts/cleanup_membership_duplicates_db_only.py
```

Перед запуском **обовʼязково** зробити бекап БД:

```bash
cp post_watchdog.sqlite3 post_watchdog.sqlite3.bak
```

### Коли корисно

- Щоб база “казала правду” щодо того, хто є в каналі як основна сесія, ще до зміни реальних підписок у Telegram.
- Якщо потрібно синхронізувати логіку всередині застосунку з новим правилом “primary‑сесія одна”.

---

## 4. `scripts/cleanup_membership_duplicates_full.py`

### Призначення

Повноцінна чистка:

1. Виходить із дубльованих каналів у Telegram для всіх акаунтів, крім primary (`tg_session`).
2. Після цього чистить таблицю `membership`, видаляючи відповідні рядки.

Скрипт використовує `membership_duplicates.json`, тобто працює на основі зафіксованого списку дублів.

### Основні параметри й константи

- `BASE_DIR` — шлях до кореня проєкту (де лежать `.session` та БД).
- `DB_PATH` — шлях до `post_watchdog.sqlite3`.
- `DUP_JSON_PATH` — шлях до `membership_duplicates.json`.
- `PRIMARY_ACCOUNT = "tg_session"` — primary‑акаунт, який **не відписуємо**.
- `API_ID`, `API_HASH` — Telegram API‑ключі (беруться з env або задаються в коді).
- `ACCOUNT_TO_SESSION` — мапа:

  ```python
  {
      "tg_session": "tg_session",
      "tg_session_2": "tg_session_2",
      "tg_session_3": "tg_session_3",
      "tg_session_4": "tg_session_4",
      "tg_session_2.session": "tg_session_2",
      "tg_session_3.session": "tg_session_3",
      "tg_session_4.session": "tg_session_4",
  }
  ```

  Вона потрібна, щоб зіставити значення `membership.account` з реальними іменами `.session` файлів (без розширення).

- `LEAVE_DELAY_SEC` — затримка між відписками (щоб не ловити flood‑обмеження Telegram).

### Як працює

1. **Завантаження дублів**  
   Читає `membership_duplicates.json` та перетворює ключі каналів на `int`.

2. **Побудова плану відписок**  
   Для кожного `channel_id`:

   - дивиться, які `account` там є;
   - якщо серед них є `PRIMARY_ACCOUNT`, тоді всі інші `account` додає в словник:

     ```python
     to_leave[acc].add(channel_id)
     ```

   У результаті отримуємо структуру:

   ```python
   {
     "tg_session_2": {1158045480, 1175960848, ...},
     "tg_session_4": {1754988582, 2197552359, ...}
   }
   ```

3. **Показ плану і підтвердження**  
   Виводить у консоль:

   - по кожному акаунту — скільки каналів буде очищено;

   й очікує явного підтвердження:

   ```text
   Щоб ПРОДОВЖИТИ і реально вийти з каналів, набери 'YES':
   ```

4. **Вихід із каналів у Telegram (`leave_for_account`)**

   Для кожного акаунта з `to_leave`:

   - обчислює `session_name = ACCOUNT_TO_SESSION[account]`;
   - формує повний шлях до сесії:

     ```python
     session_path = os.path.join(BASE_DIR, f"{session_name}.session")
     ```

   - створює `TelegramClient(session_path, API_ID, API_HASH)`;
   - `await client.start()`;
   - в циклі по `channel_ids` робить:

     ```python
     await client.delete_dialog(channel_id)
     await asyncio.sleep(LEAVE_DELAY_SEC)
     ```

   - у випадку помилок (наприклад, приватний канал, з якого вже вигнали) виводить `RPCError`, але продовжує обробку інших каналів.

5. **Чистка таблиці `membership`**

   Після відписок:

   - відкриває `post_watchdog.sqlite3`;
   - для кожного `(account, channel_id)` із `to_leave` виконує:

     ```sql
     DELETE FROM membership WHERE channel_id = ? AND account = ?;
     ```

   - підсумовує, скільки рядків було видалено.

### Використання

1. Переконатися, що:

   - згенерований `membership_duplicates.json` (`export_membership_duplicates.py`);
   - у корені проєкту є всі `.session` файли.

2. Зробити бекап БД:

   ```bash
   cp post_watchdog.sqlite3 post_watchdog.sqlite3.before_full_cleanup.bak
   ```

3. Запустити:

   ```bash
   python scripts/cleanup_membership_duplicates_full.py
   ```

4. Переглянути план, підтвердити введенням `YES`.

5. Після завершення — перевірити:

   ```bash
   python scripts/list_membership_duplicates.py
   ```

   — дублікати мають зникнути.

### Коли корисно

- Коли потрібно **фактично розвантажити ліміт** на кількість приєднаних каналів для не‑primary акаунтів.
- Коли треба підтримувати консистентність між Telegram‑станом (де сесія реально підписана/не підписана) і таблицею `membership`.

---

## 5. `scripts/count_channels_per_session.py`

### Призначення

Порахувати поточну кількість каналів/супергруп, де кожна сесія реально є в Telegram. Це дозволяє оцінити, наскільки розвантажився ліміт після чистки.

### Як працює

1. Для кожного `session_name` із списку `SESSIONS`:

   - формує шлях до файлу: `BASE_DIR / f"{session_name}.session"`;
   - запускає `TelegramClient(session_path, API_ID, API_HASH)`;
   - проходиться по всіх `dialog`:

     ```python
     async for dialog in client.iter_dialogs():
         if isinstance(dialog.entity, Channel):
             channels.add(dialog.entity.id)
     ```

   - виводить кількість знайдених `Channel`.

2. У кінці друкує зведену таблицю:

   ```text
   Підсумок по сесіях:
     tg_session: N каналів/супергруп
     tg_session_2: M каналів/супергруп
     ...
   ```

### Використання

```bash
python scripts/count_channels_per_session.py
```

### Коли корисно

- Після `cleanup_membership_duplicates_full.py` — подивитися, скільки каналів залишилося на кожному акаунті.
- Для контролю, щоб не наблизитися знову до ліміту Telegram по кількості “joined” каналів.

---

## Рекомендована типова послідовність дій

1. **Аналіз**:

   - `python scripts/list_membership_duplicates.py`  
     Подивитися, чи є дублікати й які саме.

2. **Експорт дублів**:

   - `python scripts/export_membership_duplicates.py`  
     Зберегти `membership_duplicates.json`.

3. **(Опційно/разово) Чистка тільки БД**:

   - `python scripts/cleanup_membership_duplicates_db_only.py`  
     Привести `membership` до стану “тільки `tg_session` як primary”.

4. **Повна чистка (Telegram + БД)**:

   - `python scripts/cleanup_membership_duplicates_full.py`  
     Вийти з каналів для не‑primary акаунтів і видалити відповідні записи з `membership`.

5. **Перевірка**:

   - `python scripts/list_membership_duplicates.py`  
     Переконатися, що дублікати відсутні.
   - `python scripts/count_channels_per_session.py`  
     Подивитися, скільки каналів залишилось на кожній сесії.

Ця група інструментів дозволяє:

- тримати таблицю `membership` у коректному стані;
- уникати дублювання підписок між сесіями;
- керовано знижувати навантаження на Telegram‑ліміти для не‑primary акаунтів.