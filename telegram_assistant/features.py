"""Capabilities behind the single Telegram tool. No automatic sending."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import secrets
import zipfile
from xml.etree import ElementTree

from telethon import functions, types, utils
from .service import SearchService, bounded_limit, message_data, peer
from .helpers import date_value, positive, parse_link

FILTERS = {'todos': types.InputMessagesFilterEmpty, 'pdf': types.InputMessagesFilterDocument,
           'documentos': types.InputMessagesFilterDocument, 'fotos': types.InputMessagesFilterPhotos,
           'videos': types.InputMessagesFilterVideo, 'audios': types.InputMessagesFilterMusic,
           'voz': types.InputMessagesFilterVoice, 'enlaces': types.InputMessagesFilterUrl,
           'fijados': types.InputMessagesFilterPinned}


class Features(SearchService):
    def __init__(self, client, store):
        super().__init__(client)
        self.store = store

    def _cursor(self, cursor, kind, signature, defaults):
        if not cursor:
            return defaults
        saved = self.store.resolve(cursor, kind)
        if saved['signature'] != signature:
            raise ValueError('El cursor pertenece a otra consulta. Conserva los parámetros originales.')
        return saved['offset']

    def _next(self, kind, signature, offset):
        return self.store.token(kind, {'signature': signature, 'offset': offset})

    def _messages(self, response, entity=None):
        entities = {utils.get_peer_id(x): x for x in [*response.users, *response.chats]}
        result = []
        for message in response.messages:
            if isinstance(message, types.MessageEmpty):
                continue
            message._finish_init(self.client, entities, entity)
            result.append(message)
        return result

    async def buscar(self, consulta='', chat=None, desde=None, hasta=None, remitente=None,
                     tipo_archivo='todos', tema_id=None, origen_guardado=None, etiqueta=None, cursor=None, limite=30):
        bounded_limit(limite)
        if tipo_archivo not in FILTERS:
            raise ValueError('tipo_archivo: ' + ', '.join(FILTERS))
        if not consulta.strip() and tipo_archivo == 'todos' and not etiqueta:
            raise ValueError('Indica una consulta o un filtro de archivo.')
        start, end = date_value(desde), date_value(hasta)
        if start and end and start >= end:
            raise ValueError('desde debe ser anterior a hasta; hasta es exclusivo.')
        if tema_id is not None:
            positive(tema_id, 'tema_id')
            if not chat:
                raise ValueError('Para un tema indica su chat.')
        if origen_guardado or etiqueta:
            if chat not in ('me', 'self'):
                raise ValueError('origen_guardado y etiqueta requieren chat=me.')
        signature = [consulta, chat, start.isoformat() if start else None,
                     end.isoformat() if end else None, remitente, tipo_archivo, tema_id, origen_guardado, etiqueta]
        offset = self._cursor(cursor, 'search', signature, {'id': 0, 'peer': None, 'rate': 0})
        entity = await self.client.get_input_entity(peer(chat)) if chat else None
        sender = await self.client.get_input_entity(peer(remitente)) if remitente else None
        # Dates are enforced again locally: Telegram date bounds are exclusive.
        kwargs = dict(q=consulta.strip(), filter=FILTERS[tipo_archivo](),
                      min_date=start - timedelta(seconds=1) if start else None, max_date=end,
                      offset_id=offset['id'], limit=limite)
        if entity:
            response = await self.client(functions.messages.SearchRequest(
                peer=entity, add_offset=0, max_id=0, min_id=0, hash=0,
                from_id=sender, top_msg_id=tema_id,
                saved_peer_id=await self.client.get_input_entity(peer(origen_guardado)) if origen_guardado else None,
                saved_reaction=[types.ReactionEmoji(etiqueta)] if etiqueta else None, **kwargs))
        else:
            offset_peer = await self.client.get_input_entity(offset['peer']) if offset['peer'] else types.InputPeerEmpty()
            response = await self.client(functions.messages.SearchGlobalRequest(
                offset_peer=offset_peer, offset_rate=offset['rate'], **kwargs))
        messages = self._messages(response, entity)
        sender_id = utils.get_peer_id(sender) if sender else None
        results = []
        for message in messages:
            if sender_id is not None and message.sender_id != sender_id:
                continue
            if start and message.date < start or end and message.date >= end:
                continue
            data = message_data(message)
            if tipo_archivo == 'pdf' and not (data['file'] and (
                    data['file']['mime_type'] == 'application/pdf' or
                    (data['file']['name'] or '').lower().endswith('.pdf'))):
                continue
            results.append(data)
        next_cursor = None
        if messages:
            last = messages[-1]
            next_cursor = self._next('search', signature,
                                     {'id': last.id, 'peer': last.chat_id,
                                      'rate': getattr(response, 'next_rate', 0) or 0})
        return {'messages': results, 'next_cursor': next_cursor,
                'scanned': len(messages), 'reported_total': getattr(response, 'count', None),
                'coverage': 'Página de búsqueda de Telegram; los filtros locales pueden dejar páginas vacías. Continúa mientras exista next_cursor.',
                'date_bounds': 'desde inclusivo, hasta exclusivo; fechas sin zona usan America/Lima.'}

    async def chats_avanzados(self, consulta='', tipo='todos', archivados=None,
                              solo_pendientes=False, carpeta_id=None, cursor=None, limite=30):
        bounded_limit(limite)
        if tipo not in ('todos', 'usuarios', 'grupos', 'canales'):
            raise ValueError('tipo: todos, usuarios, grupos o canales.')
        if archivados is not None and not isinstance(archivados, bool):
            raise ValueError('archivados debe ser true, false o null.')
        signature = [consulta, tipo, archivados, solo_pendientes, carpeta_id]
        offset = self._cursor(cursor, 'chats', signature,
                              {'id': 0, 'peer': None, 'date': None, 'seen': []})
        folder = None
        if carpeta_id is not None:
            positive(carpeta_id, 'carpeta_id')
            response = await self.client(functions.messages.GetDialogFiltersRequest())
            folder = next((f for f in response.filters if getattr(f, 'id', None) == carpeta_id), None)
            if not isinstance(folder, types.DialogFilter):
                raise ValueError('Carpeta no encontrada o carpeta compartida no compatible con este filtro.')
        seen = set(offset['seen'])
        kwargs = dict(limit=100, offset_date=date_value(offset['date']), offset_id=offset['id'],
                      offset_peer=await self.client.get_input_entity(offset['peer']) if offset['peer'] else types.InputPeerEmpty(),
                      ignore_pinned=bool(offset['id']))
        if archivados is not None:
            kwargs['folder'] = 1 if archivados else 0
        results, scanned, last = [], 0, None
        async for dialog in self.client.iter_dialogs(**kwargs):
            scanned += 1
            last = dialog
            if dialog.id in seen:
                continue
            seen.add(dialog.id)
            kind = 'usuarios' if dialog.is_user else ('grupos' if dialog.is_group else 'canales')
            username = getattr(dialog.entity, 'username', '') or ''
            if consulta.casefold() not in ((dialog.name or '') + ' ' + username).casefold():
                continue
            if tipo != 'todos' and kind != tipo:
                continue
            if solo_pendientes and not dialog.unread_count and not getattr(dialog.dialog, 'unread_mentions_count', 0):
                continue
            if folder and not self._in_folder(dialog, folder):
                continue
            results.append({'id': dialog.id, 'name': dialog.name, 'username': username or None,
                            'type': kind, 'archived': dialog.archived, 'unread_count': dialog.unread_count,
                            'mentions': getattr(dialog.dialog, 'unread_mentions_count', 0),
                            'latest': message_data(dialog.message) if dialog.message else None})
            if len(results) >= limite:
                break
        next_cursor = None
        if last and (scanned == 100 or len(results) == limite) and last.message:
            pinned = bool(getattr(last.dialog, 'pinned', False))
            next_cursor = self._next('chats', signature, {'id': 0 if pinned else last.message.id,
                'peer': None if pinned else last.id,
                'date': None if pinned else last.message.date.isoformat(), 'seen': list(seen)})
        return {'chats': results, 'scanned': scanned, 'next_cursor': next_cursor,
                'coverage': 'Hasta 100 chats revisados por página. La lista puede cambiar durante la paginación.'}

    def _in_folder(self, dialog, folder):
        pid = dialog.id
        def ids(items):
            return {utils.get_peer_id(x) for x in items}
        if pid in ids(folder.exclude_peers):
            return False
        if pid in ids([*folder.include_peers, *folder.pinned_peers]):
            return True
        settings = getattr(dialog.dialog, 'notify_settings', None)
        mute_until = getattr(settings, 'mute_until', None)
        if getattr(folder, 'exclude_muted', False) and mute_until and mute_until > datetime.now(timezone.utc):
            return False
        if getattr(folder, 'exclude_read', False) and not dialog.unread_count:
            return False
        if getattr(folder, 'exclude_archived', False) and dialog.archived:
            return False
        entity = dialog.entity
        if dialog.is_user:
            if getattr(entity, 'bot', False):
                return bool(folder.bots)
            return bool(folder.contacts if getattr(entity, 'contact', False) else folder.non_contacts)
        return bool(folder.groups if dialog.is_group else folder.broadcasts)

    async def mensaje(self, chat, mensaje_id):
        positive(mensaje_id)
        message = await self.client.get_messages(peer(chat), ids=mensaje_id)
        if not message or isinstance(message, types.MessageEmpty):
            raise ValueError('Mensaje inexistente o no accesible.')
        return {'message': message_data(message)}

    async def contexto(self, chat, mensaje_id, anteriores=5, posteriores=5):
        positive(mensaje_id)
        for value in (anteriores, posteriores):
            positive(value, 'ventana', zero=True)
            if value > 30:
                raise ValueError('Cada ventana de contexto admite hasta 30 mensajes.')
        entity = peer(chat)
        anchor = await self.client.get_messages(entity, ids=mensaje_id)
        if not anchor or isinstance(anchor, types.MessageEmpty):
            raise ValueError('Mensaje inexistente o no accesible.')
        before = [m async for m in self.client.iter_messages(entity, limit=anteriores, offset_id=mensaje_id)] if anteriores else []
        after = [m async for m in self.client.iter_messages(entity, limit=posteriores, min_id=mensaje_id, reverse=True)] if posteriores else []
        reply = None
        if anchor.reply_to_msg_id:
            reply = await anchor.get_reply_message()
        return {'messages': [message_data(m) for m in [*reversed(before), anchor, *after]],
                'replied_message': message_data(reply) if reply else None,
                'anchor_id': mensaje_id, 'coverage': 'Ventana de la conversación, no todo el hilo.'}

    async def historial(self, chat, limite=30, antes_de_id=0, tema_id=None):
        bounded_limit(limite)
        positive(antes_de_id, 'antes_de_id', zero=True)
        kwargs = dict(limit=limite, offset_id=antes_de_id)
        if tema_id:
            kwargs['reply_to'] = positive(tema_id, 'tema_id')
        messages = [m async for m in self.client.iter_messages(peer(chat), **kwargs)]
        return {'messages': [message_data(m) for m in messages],
                'next_before_id': messages[-1].id if messages else None}

    async def enlace(self, url):
        chat, mid = parse_link(url)
        return await self.mensaje(chat, mid)

    async def pendientes(self, cursor=None, limite=20):
        return await self.chats_avanzados(solo_pendientes=True, cursor=cursor, limite=limite)

    async def menciones(self, chat, antes_de_id=0, limite=30):
        bounded_limit(limite)
        positive(antes_de_id, 'antes_de_id', zero=True)
        entity = await self.client.get_input_entity(peer(chat))
        response = await self.client(functions.messages.GetUnreadMentionsRequest(
            peer=entity, offset_id=antes_de_id, add_offset=0, limit=limite, max_id=0, min_id=0))
        messages = self._messages(response, entity)
        return {'messages': [message_data(m) for m in messages],
                'next_before_id': messages[-1].id if messages else None,
                'note': 'Consulta menciones pendientes sin marcarlas como leídas.'}

    async def temas(self, chat, consulta='', antes_de_id=0, antes_de_tema=0, antes_de_fecha=None, limite=30):
        bounded_limit(limite)
        positive(antes_de_id, 'antes_de_id', zero=True)
        positive(antes_de_tema, 'antes_de_tema', zero=True)
        entity = await self.client.get_input_entity(peer(chat))
        response = await self.client(functions.messages.GetForumTopicsRequest(
            peer=entity, q=consulta or None, offset_date=date_value(antes_de_fecha),
            offset_id=antes_de_id, offset_topic=antes_de_tema, limit=limite))
        top_dates = {m.id: m.date for m in response.messages if getattr(m, 'date', None)}
        topics = [{'id': t.id, 'title': getattr(t, 'title', None),
                   'top_message': getattr(t, 'top_message', None),
                   'unread_count': getattr(t, 'unread_count', None),
                   'date': t.date.isoformat() if getattr(t, 'date', None) else None,
                   'last_message_date': top_dates[t.top_message].isoformat() if getattr(t, 'top_message', None) in top_dates else None}
                  for t in response.topics]
        return {'topics': topics, 'count': response.count,
                'next': {'antes_de_id': topics[-1]['top_message'], 'antes_de_tema': topics[-1]['id'],
                         'antes_de_fecha': topics[-1]['date'] if getattr(response, 'order_by_create_date', False) else topics[-1]['last_message_date']} if topics else None}

    async def respuestas(self, chat, mensaje_id, antes_de_id=0, limite=30):
        positive(mensaje_id)
        return await self.historial(chat, limite, antes_de_id, tema_id=mensaje_id)

    async def canales_publicos(self, consulta, limite=20):
        bounded_limit(limite)
        if not consulta.strip():
            raise ValueError('Indica un nombre o usuario público.')
        response = await self.client(functions.contacts.SearchRequest(q=consulta, limit=limite))
        return {'chats': [{'id': utils.get_peer_id(c), 'name': c.title,
                          'username': getattr(c, 'username', None)} for c in response.chats],
                'coverage': 'Descubrimiento público de Telegram, sin unirse a chats. No busca todo su contenido.'}

    async def carpetas(self):
        response = await self.client(functions.messages.GetDialogFiltersRequest())
        return {'folders': [{'id': getattr(f, 'id', 0),
                             'title': getattr(getattr(f, 'title', None), 'text', ''),
                             'shared': isinstance(f, types.DialogFilterChatlist)} for f in response.filters]}

    async def guardados(self, limite=30, antes_de_id=0, consulta=None):
        if consulta is not None:
            return await self.buscar(consulta=consulta, chat='me', limite=limite)
        return await self.historial('me', limite, antes_de_id)

    async def etiquetas_guardados(self):
        response = await self.client(functions.messages.GetSavedReactionTagsRequest(hash=0))
        return {'tags': [{'title': getattr(t, 'title', None), 'count': t.count,
                           'emoji': getattr(t.reaction, 'emoticon', None),
                           'custom_emoji_id': getattr(t.reaction, 'document_id', None)} for t in response.tags],
                'note': 'Disponibilidad sujeta a tu cuenta de Telegram. buscar admite etiquetas de emoji Unicode.'}

    async def programados(self, chat, limite=30):
        bounded_limit(limite)
        messages = await self.client.get_messages(peer(chat), limit=limite, scheduled=True)
        return {'messages': [message_data(m) for m in messages], 'note': 'Mensajes programados de este chat.'}

    async def origenes_guardados(self, limite=30, cursor=None):
        bounded_limit(limite)
        offset = self._cursor(cursor, 'saved', [], {'id': 0, 'peer': None, 'date': None})
        response = await self.client(functions.messages.GetSavedDialogsRequest(
            offset_date=date_value(offset['date']), offset_id=offset['id'],
            offset_peer=await self.client.get_input_entity(offset['peer']) if offset['peer'] else types.InputPeerEmpty(),
            limit=limite, hash=0, exclude_pinned=bool(cursor)))
        dialogs = response.dialogs
        messages = {m.id: m for m in self._messages(response)}
        results = [{'origin_id': utils.get_peer_id(d.peer), 'top_message': d.top_message,
                    'pinned': bool(getattr(d, 'pinned', False))} for d in dialogs]
        next_cursor = None
        if dialogs:
            last = dialogs[-1]
            top = messages.get(last.top_message)
            if top:
                next_cursor = self._next('saved', [], {'id': last.top_message,
                    'peer': utils.get_peer_id(last.peer), 'date': top.date.isoformat()})
        return {'origins': results, 'next_cursor': next_cursor}

    async def descargar(self, chat, mensaje_id, max_mb=25):
        positive(mensaje_id)
        if not isinstance(max_mb, int) or not 1 <= max_mb <= 100:
            raise ValueError('max_mb debe estar entre 1 y 100.')
        message = await self.client.get_messages(peer(chat), ids=mensaje_id)
        if not message or not message.media or not message.file:
            raise ValueError('El mensaje no contiene un archivo descargable.')
        if message.file.size is None or message.file.size > max_mb * 1024 * 1024:
            raise ValueError('Archivo sin tamaño conocido o superior al límite de descarga.')
        directory = self.store.directory / 'downloads'
        directory.mkdir(exist_ok=True, mode=0o700)
        # Never trust a Telegram filename as a filesystem path.
        extension = message.file.ext or '.bin'
        if not extension.startswith('.') or not extension[1:].isalnum() or len(extension) > 12:
            extension = '.bin'
        path = directory / (secrets.token_hex(12) + extension)
        path.touch(mode=0o600)
        try:
            result = await self.client.download_media(message, file=str(path))
            if not result:
                raise ValueError('Telegram no devolvió un archivo.')
            if path.stat().st_size > max_mb * 1024 * 1024:
                raise ValueError('El archivo descargado supera el límite.')
            return {'path': str(path), 'message': message_data(message)}
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    async def indexar(self, chat, limite=30, antes_de_id=0):
        page = await self.historial(chat, limite, antes_de_id)
        for message in page['messages']:
            self.store.index(message)
        return {'indexed': len(page['messages']), 'next_before_id': page['next_before_id'],
                'coverage': 'Solo esta página de texto. Audios y contenido de archivos se incorporan bajo demanda.'}

    async def buscar_local(self, consulta, chat=None, limite=30):
        bounded_limit(limite)
        cid = await self.client.get_peer_id(peer(chat)) if chat and self.client else chat
        return {'messages': self.store.search(consulta, cid, limite),
                'coverage': 'Índice local de contenido incorporado; búsqueda textual, no semántica.'}

    async def extraer_documento(self, chat, mensaje_id):
        cid = await self.client.get_peer_id(peer(chat))
        cached = self.store.cached(cid, mensaje_id, 'documento')
        if cached is not None:
            return {'text': cached, 'cached': True, 'chat_id': cid, 'id': mensaje_id}
        download = await self.descargar(chat, mensaje_id, max_mb=25)
        path, data = Path(download['path']), download['message']
        mime = (data['file'] or {}).get('mime_type', '') or ''
        def extract():
            if path.suffix.lower() == '.pdf' or mime == 'application/pdf':
                from pypdf import PdfReader
                reader = PdfReader(path)
                if len(reader.pages) > 200:
                    raise ValueError('La extracción admite hasta 200 páginas.')
                return '\n'.join((p.extract_text() or '') for p in reader.pages)
            if path.suffix.lower() == '.docx':
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo('word/document.xml')
                    if info.file_size > 10 * 1024 * 1024:
                        raise ValueError('Documento demasiado grande para extraer.')
                    root = ElementTree.fromstring(archive.read(info))
                    return '\n'.join(''.join(p.itertext()) for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
            if mime.startswith('text/') or path.suffix.lower() in ('.txt', '.csv', '.md'):
                return path.read_text(encoding='utf-8', errors='replace')
            raise ValueError('Extracción disponible para PDF con texto, DOCX, TXT, CSV y Markdown; sin OCR.')
        text = await asyncio.to_thread(extract)
        text = text[:500000]
        self.store.index(data, text, 'documento')
        return {'text': text, 'path': str(path), 'indexed': True, 'source': 'documento',
                'note': 'Extracción limitada a 500000 caracteres; PDFs escaneados requieren OCR externo.'}

    async def transcribir(self, chat, mensaje_id, motor='telegram', modelo='small', idioma='es'):
        positive(mensaje_id)
        if motor not in ('telegram', 'local'):
            raise ValueError('motor: telegram o local.')
        cid = await self.client.get_peer_id(peer(chat))
        source = 'audio:telegram' if motor == 'telegram' else f'audio:local:{modelo}:{idioma}'
        cached = self.store.cached(cid, mensaje_id, source)
        if cached is not None:
            return {'transcript': cached, 'cached': True, 'chat_id': cid, 'id': mensaje_id}
        message = await self.client.get_messages(peer(chat), ids=mensaje_id)
        if not message or not (message.voice or message.audio or message.video):
            raise ValueError('Selecciona un mensaje de voz, audio o video.')
        if motor == 'telegram':
            response = await self.client(functions.messages.TranscribeAudioRequest(
                peer=await self.client.get_input_entity(peer(chat)), msg_id=mensaje_id))
            if response.pending:
                return {'pending': True, 'note': 'Telegram sigue procesando. Repite esta operación más tarde.'}
            text = response.text
        else:
            if modelo not in ('tiny', 'base', 'small', 'medium', 'large-v3', 'large-v3-turbo'):
                raise ValueError('Modelo local no permitido.')
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                return {'available': False, 'code': 'local_transcription_not_installed',
                        'note': 'Instala el extra audio en Python 3.11 o 3.12 para usar Whisper local.'}
            download = await self.descargar(chat, mensaje_id, max_mb=25)
            def transcribe():
                engine = WhisperModel(modelo, device='cpu', compute_type='int8',
                                      download_root=str(self.store.directory / 'models'))
                segments, info = engine.transcribe(download['path'], language=idioma or None, vad_filter=True)
                return ' '.join(segment.text for segment in segments)
            text = await asyncio.to_thread(transcribe)
        self.store.index(message_data(message), text, source)
        return {'transcript': text, 'indexed': True, 'source': source,
                'note': 'Transcripción automática; puede contener errores. El motor Telegram está sujeto a límites de cuenta.'}

    async def novedades(self, chat, limite=30):
        bounded_limit(limite)
        cid = await self.client.get_peer_id(peer(chat))
        key = f'checkpoint:{cid}'
        previous = self.store.get(key)
        if previous is None:
            messages = [m async for m in self.client.iter_messages(peer(chat), limit=1)]
            mid = messages[0].id if messages else 0
            self.store.set(key, mid)
            return {'initialized': True, 'last_id': mid, 'messages': [],
                    'coverage': 'Punto inicial creado ahora; no se considera el historial anterior como novedad.'}
        messages = [m async for m in self.client.iter_messages(peer(chat), min_id=previous, reverse=True, limit=limite)]
        if messages:
            self.store.set(key, messages[-1].id)
        return {'messages': [message_data(m) for m in messages], 'previous_id': previous,
                'last_id': messages[-1].id if messages else previous, 'may_have_more': len(messages) == limite,
                'coverage': 'Mensajes nuevos consultados bajo demanda. No registra borrados ni todas las ediciones; no hay monitor automático activo.'}

    async def exportar(self, chat=None, trabajo_id=None, formato='json', limite=100):
        bounded_limit(limite)
        if formato not in ('json', 'markdown'):
            raise ValueError('formato: json o markdown.')
        if trabajo_id:
            if not isinstance(trabajo_id, str) or len(trabajo_id) != 24 or not all(c in '0123456789abcdef' for c in trabajo_id):
                raise ValueError('trabajo_id inválido.')
            job = self.store.get('export:' + trabajo_id)
            if not job:
                raise ValueError('Exportación no encontrada.')
        else:
            if not chat:
                raise ValueError('Indica chat para iniciar la exportación.')
            cid = await self.client.get_peer_id(peer(chat))
            trabajo_id = secrets.token_hex(12)
            job = {'chat': str(cid), 'before': 0, 'format': formato, 'count': 0, 'complete': False,
                   'messages': []}
        if not job['complete']:
            page = await self.historial(job['chat'], limite, job['before'])
            if job['count'] + len(page['messages']) > 100000:
                raise ValueError('La exportación alcanza el límite de 100000 mensajes. Divide el historial en varios archivos.')
            job['messages'].extend(page['messages'])
            job['count'] += len(page['messages'])
            job['before'] = page['next_before_id'] or job['before']
            job['complete'] = not page['messages']
            self.store.set('export:' + trabajo_id, job)
        directory = self.store.directory / 'exports'
        directory.mkdir(exist_ok=True, mode=0o700)
        path = directory / (trabajo_id + ('.json' if job['format'] == 'json' else '.md'))
        ordered = sorted(job['messages'], key=lambda m: m['id'])
        if job['format'] == 'json':
            content = json.dumps({'chat': job['chat'], 'complete': job['complete'],
                                  'messages': ordered}, ensure_ascii=False, indent=2)
        else:
            content = f"# Conversación {job['chat']}\n\nCobertura completa: {job['complete']}\n\n"
            content += '\n\n'.join(f"## {m['date_lima']} · {m['sender_id']} · mensaje {m['id']}\n\n{m['text']}\n\nReferencia: {m['url'] or 'chat '+str(m['chat_id'])+' / mensaje '+str(m['id'])}" for m in ordered)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(path)
        return {'job_id': trabajo_id, 'path': str(path), 'exported': job['count'], 'complete': job['complete'],
                'note': 'Repite con trabajo_id para continuar. Exporta texto y metadatos, no archivos. Historial vivo, no una instantánea inmutable.'}

    async def borradores(self, limite=30):
        bounded_limit(limite)
        results = []
        async for draft in self.client.iter_drafts():
            results.append({'chat_id': utils.get_peer_id(draft.entity), 'text': draft.text,
                            'date': draft.date.isoformat() if draft.date else None})
            if len(results) >= limite:
                break
        return {'drafts': results, 'coverage': f'Hasta {limite} borradores.'}

    async def preparar_accion(self, operacion, chat=None, texto=None, mensaje_id=None,
                             fecha=None, titulo=None, chats=None, carpeta_id=None):
        allowed = ('enviar', 'borrador', 'archivar', 'desarchivar', 'silenciar', 'activar_notificaciones', 'crear_carpeta', 'actualizar_carpeta')
        if operacion not in allowed:
            raise ValueError('operacion: ' + ', '.join(allowed))
        if operacion in ('enviar', 'borrador') and (not texto or not texto.strip() or len(texto) > 4096):
            raise ValueError('texto debe contener entre 1 y 4096 caracteres.')
        target, name, username = None, None, None
        if operacion not in ('crear_carpeta', 'actualizar_carpeta'):
            if not chat:
                raise ValueError('Indica el destinatario mediante ID, @usuario o me.')
            entity = await self.client.get_entity(peer(chat))
            target = utils.get_peer_id(entity)
            name = getattr(entity, 'title', None) or getattr(entity, 'first_name', None)
            username = getattr(entity, 'username', None)
        schedule = date_value(fecha)
        if schedule and schedule <= datetime.now(timezone.utc):
            raise ValueError('fecha debe ser futura.')
        if fecha and operacion not in ('enviar', 'silenciar'):
            raise ValueError('fecha solo aplica a envío programado o fin de silencio.')
        if mensaje_id is not None:
            positive(mensaje_id)
            if operacion not in ('enviar', 'borrador'):
                raise ValueError('mensaje_id solo aplica a respuestas o borradores.')
            await self.mensaje(str(target), mensaje_id)
        folder_peers = None
        if operacion in ('crear_carpeta', 'actualizar_carpeta'):
            if not titulo or not titulo.strip() or len(titulo) > 12 or not chats or len(chats) > 100:
                raise ValueError('Indica título de 1 a 12 caracteres y entre 1 y 100 chats.')
            folder_peers = [await self.client.get_peer_id(peer(c)) for c in chats]
            response = await self.client(functions.messages.GetDialogFiltersRequest())
            existing = [f for f in response.filters if hasattr(f, 'id')]
            if operacion == 'crear_carpeta':
                carpeta_id = max([1, *[f.id for f in existing]]) + 1
            elif carpeta_id not in [f.id for f in existing] or carpeta_id < 2:
                raise ValueError('carpeta_id no corresponde a una carpeta editable.')
        payload = {'operacion': operacion, 'target': target, 'name': name, 'username': username,
                   'texto': texto, 'mensaje_id': mensaje_id, 'fecha': schedule.isoformat() if schedule else None,
                   'titulo': titulo, 'chats': folder_peers, 'carpeta_id': carpeta_id,
                   'random_id': secrets.randbits(63)}
        token = self.store.token('action', payload, ttl=600)
        return {'preview': payload, 'confirmation_token': token, 'expires_in_seconds': 600,
                'note': 'Ejecutar solo cuando el usuario haya pedido esta acción o aprobado la vista previa. Actualizar una carpeta reemplaza sus reglas por esta lista explícita de chats.'}

    async def ejecutar_accion(self, comprobante, autorizado=False):
        if autorizado is not True:
            raise ValueError('Hace falta autorización explícita del usuario para ejecutar la acción preparada.')
        payload = self.store.resolve(comprobante, 'action')
        # Durable delivery receipt prevents a retry from sending twice.
        record = self.store.get('action:' + comprobante)
        if record and record.get('state') == 'done':
            return record['result']
        if record:
            return {'state': 'uncertain', 'note': 'La operación pudo ejecutarse. Revisa Telegram; no se repite automáticamente.'}
        self.store.set('action:' + comprobante, {'state': 'started'})
        target = await self.client.get_input_entity(payload['target']) if payload['target'] is not None else None
        operation = payload['operacion']
        try:
            if operation == 'enviar':
                request = functions.messages.SendMessageRequest(
                    peer=target, message=payload['texto'], random_id=payload['random_id'],
                    reply_to=types.InputReplyToMessage(payload['mensaje_id']) if payload['mensaje_id'] else None,
                    schedule_date=date_value(payload['fecha']), no_webpage=True)
                response = await self.client(request)
                # Extract a receipt without exposing transport internals.
                mid = getattr(response, 'id', None)
                if mid is None:
                    mid = next((u.id for u in getattr(response, 'updates', []) if isinstance(u, types.UpdateMessageID)), None)
                result = {'sent': True, 'scheduled': bool(payload['fecha']), 'chat_id': payload['target'], 'message_id': mid}
            elif operation == 'borrador':
                await self.client(functions.messages.SaveDraftRequest(peer=target, message=payload['texto'],
                    reply_to=types.InputReplyToMessage(payload['mensaje_id']) if payload['mensaje_id'] else None))
                result = {'saved': True, 'chat_id': payload['target']}
            elif operation in ('archivar', 'desarchivar'):
                await self.client.edit_folder(target, folder=1 if operation == 'archivar' else 0)
                result = {'updated': True, 'chat_id': payload['target']}
            elif operation in ('silenciar', 'activar_notificaciones'):
                until = date_value(payload['fecha']) if payload['fecha'] else datetime(2038, 1, 1, tzinfo=timezone.utc)
                if operation == 'activar_notificaciones':
                    until = datetime(1970, 1, 1, tzinfo=timezone.utc)
                await self.client(functions.account.UpdateNotifySettingsRequest(
                    peer=types.InputNotifyPeer(target), settings=types.InputPeerNotifySettings(mute_until=until)))
                result = {'updated': True, 'chat_id': payload['target']}
            else:
                entities = [await self.client.get_input_entity(c) for c in payload['chats']]
                if operation == 'crear_carpeta':
                    response = await self.client(functions.messages.GetDialogFiltersRequest())
                    if payload['carpeta_id'] in [getattr(f, 'id', None) for f in response.filters]:
                        raise ValueError('La lista de carpetas cambió; prepara la acción de nuevo.')
                await self.client(functions.messages.UpdateDialogFilterRequest(
                    id=payload['carpeta_id'], filter=types.DialogFilter(id=payload['carpeta_id'],
                        title=types.TextWithEntities(payload['titulo'], []), pinned_peers=[],
                        include_peers=entities, exclude_peers=[])))
                result = {'updated': True, 'folder_id': payload['carpeta_id']}
        except Exception:
            # Preserve uncertain state; no automatic resend after transport errors.
            raise
        self.store.set('action:' + comprobante, {'state': 'done', 'result': result})
        return result
