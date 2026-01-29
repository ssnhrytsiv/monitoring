from telethon import TelegramClient
from telethon.network.connection import ConnectionTcpAbridged
import asyncio
import pathlib

# Жорстко прописані значення; за потреби змініть тут
API_ID = 37799936
API_HASH = "734260d86b110fa11eb9263bd9963fc4"
SESSION_NAME = "tg_session_qr"
SESSION_FILE = "tg_session_11"


async def main():
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH, connection=ConnectionTcpAbridged)
    await client.connect()

    try:
        import qrcode
    except Exception:
        raise SystemExit("Встанови залежність: pip install 'qrcode[pil]'")

    qr_login = await client.qr_login()

    while True:
        url = qr_login.url
        img = qrcode.make(url)
        img.save("qr_login.png")
        print("Новий QR збережено у:", pathlib.Path("qr_login.png").resolve())
        print("В Telegram: Налаштування → Пристрої → Сканувати QR (є 60 сек).")

        try:
            await qr_login.wait(timeout=60)  # 60 сек на скан
            break
        except asyncio.TimeoutError:
            qr_login = await qr_login.recreate()
            print("QR протермінувався, генерую новий…")

    print("Авторизовано, сесію збережено:", getattr(client.session, "filename", SESSION_NAME))
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
