# Telegram Post Watchdog — v13 (Full)

## Можливості
- Ручне додавання каналів у монітор (з автопідпискою, тротлінгом і FLOOD_WAIT).
- Еталонний пост: точний/нормалізований/regex/фаззі пошук (caption або текст).
- ARM: чекання появи поста (find_window), далі 24h-моніторинг переглядів (mon_window).
- Jobs (пострічковий лог) + Summary (агрегат): Google Sheets.
- Автосповіщення через 1 годину: «посилання (назва) - Немає поста» + Jobs=Ні.
- Періодичні статус-звіти (після старту і кожен find_interval).
- Окрема група/канал для звітів: `/report_chat set=@group` або `.env REPORT_CHAT`.

## Команди
```
/monitor_new admin=@manager start=YYYY-MM-DD cpm=120 owner=@owner [subset=o]
/monitor_links_done
/needle text="..." | link=https://t.me/source/123 [mode=exact_strict|exact_norm|fuzzy|regex] [fuzz=85]
/arm_job id=1 find_interval=30m find_window=72h mon_interval=1h mon_window=24h [mode=...] [fuzz=...]
/report_chat set=@my_reports_group
/status id=1
```

## Запуск у PyCharm
1) Створи venv → `pip install -r requirements.txt`  
2) Скопіюй `.env.example` → `.env`, заповни API_ID/API_HASH/REPORT_CHAT/Google Sheets.  
3) Run Configuration: Script path → `tg_post_watchdog.py`.  
4) Запусти ▶️, введи код із Telegram при першому запуску.
