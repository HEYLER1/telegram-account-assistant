from contextlib import asynccontextmanager
from pathlib import Path
import fcntl
import os

ROOT = Path(__file__).resolve().parent.parent


def bounded_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("El límite debe ser un entero entre 1 y 100.")
    return limit


def peer(value: str):
    value = value.strip()
    if not value:
        raise ValueError("Indica un chat mediante su ID, @usuario o 'me'.")
    return int(value) if value.lstrip('-').isdigit() else value


def new_client():
    from dotenv import load_dotenv
    from telethon import TelegramClient
    load_dotenv(ROOT / '.env')
    api_id = os.getenv('TELEGRAM_API_ID', '')
    api_hash = os.getenv('TELEGRAM_API_HASH', '')
    if not api_id.isdigit() or int(api_id) <= 0 or not api_hash:
        raise ValueError('Configura TELEGRAM_API_ID y TELEGRAM_API_HASH en .env.')
    directory = ROOT / 'sessions'
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    os.umask(0o077)
    return TelegramClient(str(directory / 'account'), int(api_id), api_hash,
                          flood_sleep_threshold=0, receive_updates=False)


@asynccontextmanager
async def connection(login=False, qr=False, require_auth=True):
    directory = ROOT / "sessions"
    directory.mkdir(mode=0o700, exist_ok=True)
    lock = open(directory / "account.lock", "a")
    (directory / "account.lock").chmod(0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("La sesión está en uso. Cierra la otra instancia e inténtalo de nuevo.") from None
    client = None
    try:
        client = new_client()
        if qr:
            import qrcode
            from telethon.errors import SessionPasswordNeededError
            from getpass import getpass
            await client.connect()
            await client.set_receive_updates(True)
            if not await client.is_user_authorized():
                code = await client.qr_login()
                image = qrcode.QRCode()
                image.add_data(code.url)
                image.print_ascii(invert=True)
                print("Escanea desde Telegram → Ajustes → Dispositivos → Vincular dispositivo.")
                try:
                    await code.wait(timeout=60)
                except SessionPasswordNeededError:
                    await client.sign_in(password=getpass("Contraseña de dos pasos: "))
        elif login:
            from getpass import getpass
            await client.start(phone=lambda: input('Número con prefijo internacional: '),
                               code_callback=lambda: getpass('Código de Telegram: '),
                               password=lambda: getpass('Contraseña de dos pasos: '))
        else:
            await client.connect()
            if require_auth and not await client.is_user_authorized():
                raise RuntimeError('Primero ejecuta telegram-asistente login en tu terminal.')
        yield client
    finally:
        try:
            if client is not None:
                await client.disconnect()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()


def message_data(message):
    from telethon import utils
    from telethon.tl.types import Channel, PeerChannel
    from datetime import timezone
    from zoneinfo import ZoneInfo
    chat = message.chat
    username = getattr(chat, 'username', None)
    chat_id = message.chat_id
    # Usernames on private users do not identify public message links.
    channel_id, peer_type = utils.resolve_id(chat_id) if chat_id is not None else (None, None)
    is_channel = isinstance(chat, Channel) or peer_type is PeerChannel
    link = None
    if is_channel and username:
        link = f'https://t.me/{username}/{message.id}'
    elif is_channel and peer_type is PeerChannel:
        link = f'https://t.me/c/{channel_id}/{message.id}'
    date = message.date
    if date and date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    file = getattr(message, 'file', None)
    kind = next((name for name in ('voice', 'video_note', 'video', 'photo', 'audio', 'document')
                 if getattr(message, name, None)), None)
    sender = getattr(message, 'sender', None)
    return {'id': message.id, 'chat_id': chat_id,
            'chat': getattr(chat, 'title', None) or getattr(chat, 'first_name', None),
            'sender_id': message.sender_id,
            'sender_name': getattr(sender, 'title', None) or getattr(sender, 'first_name', None),
            'date': date.isoformat() if date else None,
            'date_lima': date.astimezone(ZoneInfo('America/Lima')).isoformat() if date else None,
            'text': message.raw_text or '', 'has_media': bool(message.media), 'url': link,
            'reply_to_id': getattr(message, 'reply_to_msg_id', None),
            'topic_id': getattr(getattr(message, 'reply_to', None), 'reply_to_top_id', None),
            'media_type': kind, 'file': {'name': getattr(file, 'name', None),
                'size': getattr(file, 'size', None), 'mime_type': getattr(file, 'mime_type', None)} if file else None}


class SearchService:
    def __init__(self, client):
        self.client = client

    async def chats(self, query='', limit=30):
        bounded_limit(limit)
        results = []
        scanned = 0
        async for dialog in self.client.iter_dialogs(limit=1000):
            scanned += 1
            if query.casefold() in (dialog.name or '').casefold():
                results.append({'id': dialog.id, 'name': dialog.name,
                                'username': getattr(dialog.entity, 'username', None),
                                'unread_count': dialog.unread_count})
                if len(results) >= limit:
                    break
        return {'chats': results, 'scanned': scanned,
                'note': 'Se revisan hasta 1000 chats; los resultados pueden ser parciales.'}

    async def search(self, query, chat=None, limit=30):
        bounded_limit(limit)
        if not query or not query.strip():
            raise ValueError('La búsqueda no puede estar vacía.')
        messages = self.client.iter_messages(peer(chat) if chat else None,
                                             search=query.strip(), limit=limit)
        return {'messages': [message_data(m) async for m in messages],
                'note': 'Búsqueda textual de Telegram; no es búsqueda semántica ni exhaustiva de todo Telegram.'}

    async def history(self, chat, limit=30, before_id=0):
        bounded_limit(limit)
        if before_id < 0:
            raise ValueError('before_id debe ser mayor o igual a cero.')
        messages = self.client.iter_messages(peer(chat), limit=limit, offset_id=before_id)
        return {'messages': [message_data(m) async for m in messages]}
