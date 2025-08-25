# app/plugins/help_and_ping.py
from telethon import events

HELP_TEXT_MD = """\
*Доступні команди*

*Лінки (batch mode)*
- `/monitor_links_on` — увімкнути збір посилань (просто кидай повідомлення з лінками)
- `/monitor_links_off` — вимкнути збір та показати скільки назбирали
- `/debug_links` — показати зібрані посилання

*Needle (пост для пошуку)*
- `/needle_from_reply` — зроби *reply* на повідомлення з текстом/фото (підпис) — збережемо як needle
- `/needle_show` — показати поточний needle
- `/needle_clear` — очистити needle

*Моніторинг*
- `/mon_new owner=@username cpm=120` — створити монітор із поточних зібраних лінків + needle
- `/mon_start` — запустити монітор (перевіряє кожну годину протягом вікна)
- `/mon_status` — поточний стан: де вийшло/видалено/охоплення

*Технічне*
- `/help` — показати цю довідку
- `/ping` — перевірка зв’язку (має відповісти “pong”)
"""

def setup(client, control_peer, monitor_buffer):
    # фільтр: приймати команди тільки від control_peer (якщо заданий)
    dec_filter = {}
    if control_peer:
        dec_filter = dict(from_users=control_peer)

    @client.on(events.NewMessage(pattern=r'^/help$', **dec_filter))
    async def help_cmd(event):
        await event.reply(HELP_TEXT_MD, parse_mode="md")

    @client.on(events.NewMessage(pattern=r'^/ping$', **dec_filter))
    async def ping_cmd(event):
        await event.reply("pong")