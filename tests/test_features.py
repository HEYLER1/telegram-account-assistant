import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from telethon import functions, types, utils
from telegram_assistant.features import Features
from telegram_assistant.gateway import Gateway, ACTIONS, failure
from telegram_assistant.helpers import date_value, parse_link, budget_result
from telegram_assistant.service import message_data
from telegram_assistant.storage import Store

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def msg(mid=10, chat=123, text='Contrato de trabajo', sender=7):
    peer_id = types.PeerChannel(chat) if chat != 7 else types.PeerUser(chat)
    return types.Message(id=mid, peer_id=peer_id, date=NOW, message=text, from_id=types.PeerUser(sender))


class Client:
    def __init__(self):
        self.calls, self.responses, self.history_calls = [], [], []
        self._self_id = 7
        self.session = SimpleNamespace()
        self._mb_entity_cache = SimpleNamespace(get=lambda *a: None)
        self.messages = [msg(10), msg(9)]
        self.after = [msg(11), msg(12)]
        self.dialogs = []
        self.fail_send = False

    async def get_input_entity(self, entity):
        if isinstance(entity, (types.InputPeerUser, types.InputPeerChannel, types.InputPeerChat)):
            return entity
        if entity == 'me':
            return types.InputPeerSelf()
        if isinstance(entity, str) and entity.startswith('@'):
            return types.InputPeerUser(7, 99)
        number = int(entity)
        return types.InputPeerChannel(int(str(number)[4:]), 99) if str(number).startswith('-100') else types.InputPeerUser(number, 99)

    async def get_entity(self, entity):
        return types.User(id=7, first_name='Ana', username='ana', access_hash=99)

    async def get_peer_id(self, entity):
        if entity == 'me':
            return 7
        return utils.get_peer_id(await self.get_input_entity(entity)) if str(entity).lstrip('-').isdigit() else 7

    async def __call__(self, request):
        self.calls.append(request)
        if isinstance(request, functions.messages.SendMessageRequest):
            if self.fail_send:
                raise OSError('transport failure')
            return SimpleNamespace(id=55)
        if self.responses:
            return self.responses.pop(0)
        return types.messages.MessagesSlice(count=4, messages=self.messages, topics=[],
              chats=[types.Channel(id=123, title='Trabajo', photo=types.ChatPhotoEmpty(), date=NOW, megagroup=True, access_hash=99)],
              users=[types.User(id=7, first_name='Ana', access_hash=99)], next_rate=88)

    async def get_messages(self, entity, ids=None, **kwargs):
        if ids == 999:
            return None
        if kwargs.get('scheduled'):
            return []
        message = msg(ids or 10)
        message._finish_init(self, {}, await self.get_input_entity(entity))
        return message

    async def iter_messages(self, entity, **kwargs):
        self.history_calls.append((entity, kwargs))
        messages = self.after if kwargs.get('reverse') else self.messages
        for message in messages[:kwargs.get('limit', len(messages))]:
            message._finish_init(self, {}, await self.get_input_entity(entity))
            yield message

    async def iter_dialogs(self, **kwargs):
        for dialog in self.dialogs:
            yield dialog


class FeatureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.client = Client()
        self.service = Features(self.client, self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_global_cursor_keeps_peer_rate_and_message(self):
        first = await self.service.buscar('Contrato')
        await self.service.buscar('Contrato', cursor=first['next_cursor'])
        request = self.client.calls[-1]
        self.assertIsInstance(request, functions.messages.SearchGlobalRequest)
        self.assertEqual(request.offset_rate, 88)
        self.assertEqual(request.offset_id, 9)
        self.assertEqual(request.offset_peer.channel_id, 123)

    async def test_cursor_rejects_different_query(self):
        first = await self.service.buscar('Contrato')
        with self.assertRaises(ValueError):
            await self.service.buscar('Otro', cursor=first['next_cursor'])
        self.assertEqual(len(self.client.calls), 1)

    async def test_filters_dates_and_sender(self):
        result = await self.service.buscar('Contrato', chat='-100123', desde='2026-10-03', hasta='2026-10-04', remitente='7')
        request = self.client.calls[0]
        self.assertEqual(request.from_id.user_id, 7)
        self.assertEqual(request.min_date.hour, 4)  # Lima midnight minus one second
        self.assertEqual(request.min_date.minute, 59)
        self.assertEqual(len(result['messages']), 2)
        self.assertEqual(result['messages'][0]['date_lima'][11:16], '07:00')

    async def test_media_only_and_invalid_dates(self):
        result = await self.service.buscar(tipo_archivo='pdf')
        self.assertEqual(result['messages'], [])
        self.assertIsNotNone(result['next_cursor'])
        self.assertIsInstance(self.client.calls[0].filter, types.InputMessagesFilterDocument)
        with self.assertRaises(ValueError):
            await self.service.buscar('x', desde='2026-10-04', hasta='2026-10-03')

    async def test_context_orders_before_anchor_and_after(self):
        result = await self.service.contexto('-100123', 20, anteriores=2, posteriores=2)
        self.assertEqual([m['id'] for m in result['messages']], [9, 10, 20, 11, 12])
        self.assertEqual(self.client.history_calls[1][1]['min_id'], 20)
        self.assertTrue(self.client.history_calls[1][1]['reverse'])

    async def test_invalid_message_and_link(self):
        with self.assertRaises(ValueError):
            await self.service.mensaje('7', 999)
        with self.assertRaises(ValueError):
            await self.service.enlace('https://evil.example/c/123/10')
        result = await self.service.enlace('https://t.me/c/123/10')
        self.assertEqual(result['message']['id'], 10)

    async def test_saved_origin_and_tag(self):
        await self.service.buscar('Contrato', chat='me', origen_guardado='7', etiqueta='📌')
        self.assertEqual(self.client.calls[-1].saved_peer_id.user_id, 7)
        self.assertEqual(self.client.calls[-1].saved_reaction[0].emoticon, '📌')
        with self.assertRaises(ValueError):
            await self.service.buscar('Contrato', chat='7', etiqueta='📌')

    async def test_index_and_search_transcription(self):
        data = message_data(await self.client.get_messages('-100123', ids=10))
        self.store.index(data, 'El pago llegará mañana', 'audio:telegram')
        self.store.index(data, 'El pago llegará mañana', 'audio:telegram')
        result = await self.service.buscar_local('pago mañana')
        self.assertEqual(len(result['messages']), 1)
        self.assertEqual(result['messages'][0]['source'], 'audio:telegram')
        self.assertEqual(self.store.cached(data['chat_id'], 10, 'audio:telegram'), 'El pago llegará mañana')

    async def test_checkpoint_survives_calls_and_pages(self):
        first = await self.service.novedades('-100123', limite=1)
        self.assertTrue(first['initialized'])
        second = await self.service.novedades('-100123', limite=1)
        self.assertEqual(second['previous_id'], 10)
        self.assertEqual(second['last_id'], 11)
        self.assertTrue(second['may_have_more'])

    async def test_resumable_export_no_duplicate_page(self):
        first = await self.service.exportar(chat='-100123', limite=2)
        self.assertEqual(first['exported'], 2)
        self.client.messages = []
        second = await self.service.exportar(trabajo_id=first['job_id'])
        self.assertTrue(second['complete'])
        self.assertEqual(second['exported'], 2)
        self.assertEqual(Path(second['path']).stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            await self.service.exportar(trabajo_id='../../secret')

    async def test_preview_does_not_send_and_execution_has_receipt(self):
        preview = await self.service.preparar_accion('enviar', chat='@ana', texto='Hola')
        self.assertEqual(preview['preview']['target'], 7)
        self.assertEqual(self.client.calls, [])
        token = preview['confirmation_token']
        with self.assertRaises(ValueError):
            await self.service.ejecutar_accion(token)
        first = await self.service.ejecutar_accion(token, autorizado=True)
        second = await self.service.ejecutar_accion(token, autorizado=True)
        self.assertEqual(first, second)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0].message, 'Hola')

    async def test_transport_failure_never_blindly_resends(self):
        preview = await self.service.preparar_accion('enviar', chat='7', texto='Hola')
        self.client.fail_send = True
        with self.assertRaises(OSError):
            await self.service.ejecutar_accion(preview['confirmation_token'], autorizado=True)
        result = await self.service.ejecutar_accion(preview['confirmation_token'], autorizado=True)
        self.assertEqual(result['state'], 'uncertain')
        self.assertEqual(len(self.client.calls), 1)

    async def test_schedule_passed_to_telegram(self):
        preview = await self.service.preparar_accion('enviar', chat='7', texto='Hola', fecha='2099-01-01T10:00:00-05:00')
        result = await self.service.ejecutar_accion(preview['confirmation_token'], autorizado=True)
        self.assertTrue(result['scheduled'])
        self.assertEqual(self.client.calls[0].schedule_date.hour, 15)

    async def test_download_limit_blocks_before_network(self):
        with self.assertRaises(ValueError):
            await self.service.descargar('-100123', 10, max_mb=101)
        self.assertEqual(self.client.calls, [])

    async def test_unknown_transcription_engine(self):
        with self.assertRaises(ValueError):
            await self.service.transcribir('7', 10, motor='external')

    async def test_document_extraction_indexes_and_caches(self):
        path = Path(self.tmp.name) / 'contract.txt'
        path.write_text('Contrato: pago en octubre', encoding='utf-8')
        data = message_data(await self.client.get_messages('-100123', ids=10))
        data['file'] = {'mime_type': 'text/plain', 'name': 'contract.txt', 'size': 30}
        from unittest.mock import AsyncMock
        with patch.object(self.service, 'descargar', new=AsyncMock(return_value={'path':str(path), 'message':data})) as download:
            first = await self.service.extraer_documento('-100123', 10)
            second = await self.service.extraer_documento('-100123', 10)
            self.assertTrue(first['indexed'])
            self.assertTrue(second['cached'])
            self.assertEqual(download.await_count, 1)
            found = await self.service.buscar_local('octubre')
            self.assertEqual(found['messages'][0]['source'], 'documento')

    async def test_telegram_transcription_pending_then_cached(self):
        from unittest.mock import AsyncMock
        document = types.Document(id=1, access_hash=2, file_reference=b'', date=NOW,
            mime_type='audio/ogg', size=100, dc_id=1,
            attributes=[types.DocumentAttributeAudio(duration=1, voice=True)])
        message = msg(10)
        message.media = types.MessageMediaDocument(document=document)
        message._finish_init(self.client, {}, types.InputPeerChannel(123,99))
        self.client.responses = [SimpleNamespace(pending=True), SimpleNamespace(pending=False, text='Pago recibido')]
        with patch.object(self.client, 'get_messages', new=AsyncMock(return_value=message)):
            first = await self.service.transcribir('-100123', 10)
            self.assertTrue(first['pending'])
            second = await self.service.transcribir('-100123', 10)
            self.assertEqual(second['transcript'], 'Pago recibido')
            third = await self.service.transcribir('-100123', 10)
            self.assertTrue(third['cached'])
            self.assertEqual(len(self.client.calls), 2)

    async def test_folder_preview_and_update_request(self):
        response = SimpleNamespace(filters=[])
        self.client.responses = [response, response, SimpleNamespace()]
        preview = await self.service.preparar_accion('crear_carpeta', titulo='Trabajo', chats=['7'])
        self.assertEqual(preview['preview']['carpeta_id'], 2)
        result = await self.service.ejecutar_accion(preview['confirmation_token'], autorizado=True)
        self.assertEqual(result['folder_id'], 2)
        request = self.client.calls[-1]
        self.assertIsInstance(request, functions.messages.UpdateDialogFilterRequest)
        self.assertEqual(request.filter.title.text, 'Trabajo')
        self.assertEqual(request.filter.include_peers[0].user_id, 7)
        bytes(request)  # Ensures the chosen TL types serialize correctly.

    async def test_draft_and_mute_requests_serialize(self):
        for operation in ('borrador', 'silenciar', 'activar_notificaciones'):
            preview = await self.service.preparar_accion(operation, chat='7', texto='Hola' if operation=='borrador' else None)
            await self.service.ejecutar_accion(preview['confirmation_token'], autorizado=True)
            bytes(self.client.calls[-1])
        self.assertIsInstance(self.client.calls[0], functions.messages.SaveDraftRequest)
        self.assertIsInstance(self.client.calls[1], functions.account.UpdateNotifySettingsRequest)

    async def test_pinned_chats_do_not_skip_newer_unpinned_conversations(self):
        def dialog(mid, cid, pinned, name):
            message = msg(mid)
            message._finish_init(self.client, {}, types.InputPeerUser(cid,99))
            return SimpleNamespace(id=cid, name=name, entity=types.User(id=cid), is_user=True,
                is_group=False, archived=False, unread_count=0, message=message,
                dialog=SimpleNamespace(pinned=pinned, unread_mentions_count=0))
        self.client.dialogs = [dialog(1, 7, True, 'Fijado'), dialog(20, 8, False, 'Nuevo')]
        first = await self.service.chats_avanzados(limite=1)
        offset = self.store.resolve(first['next_cursor'], 'chats')['offset']
        self.assertEqual(offset['id'], 0)
        second = await self.service.chats_avanzados(limite=1, cursor=first['next_cursor'])
        self.assertEqual(second['chats'][0]['name'], 'Nuevo')

    async def test_mentions_and_topic_pagination_serialize(self):
        topic = SimpleNamespace(id=42,title='Ventas',top_message=10,unread_count=1,date=NOW)
        response = SimpleNamespace(topics=[topic],count=1,messages=[msg(10)], order_by_create_date=False)
        self.client.responses=[response]
        result=await self.service.temas('-100123')
        self.assertEqual(result['next']['antes_de_id'],10)
        self.assertEqual(result['next']['antes_de_fecha'],NOW.isoformat())
        bytes(self.client.calls[-1])
        await self.service.menciones('-100123',antes_de_id=20)
        self.assertIsInstance(self.client.calls[-1],functions.messages.GetUnreadMentionsRequest)
        bytes(self.client.calls[-1])


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.connections = 0
        self.client = Client()
        @asynccontextmanager
        async def connector(**kwargs):
            self.connections += 1
            yield self.client
        self.gateway = Gateway(Path(self.tmp.name), connector)

    def tearDown(self):
        self.gateway.close()
        self.tmp.cleanup()

    async def test_catalog_works_without_account(self):
        result = await self.gateway.call()
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['result']['actions']), len(ACTIONS))
        self.assertEqual(self.connections, 0)

    async def test_invalid_arguments_do_not_connect(self):
        for params in ({'consulta': 'x', 'limite': True}, {'consulta': 'x', 'limtie': 3}):
            result = await self.gateway.call('buscar', params)
            self.assertFalse(result['ok'])
            self.assertEqual(result['error']['code'], 'invalid_parameters')
        self.assertEqual(self.connections, 0)

    async def test_one_tool_dispatches_search(self):
        result = await self.gateway.call('buscar', {'consulta': 'Contrato'})
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(result['result']['messages']), 2)

    async def test_local_search_requires_no_connection(self):
        result = await self.gateway.call('buscar_local', {'consulta': 'nada'})
        self.assertTrue(result['ok'])
        self.assertEqual(self.connections, 0)

    async def test_unknown_action_and_negative_budget(self):
        self.assertFalse((await self.gateway.call('borrar_todo'))['ok'])
        self.assertFalse((await self.gateway.call('ayuda', presupuesto_texto=-1))['ok'])


class HelperTests(unittest.TestCase):
    def test_lima_date_and_relative(self):
        self.assertEqual(date_value('2026-10-03').hour, 5)
        self.assertEqual(date_value('ayer', NOW).day, 2)
        self.assertEqual(date_value('2026-10-03T12:00:00Z').hour, 12)

    def test_private_username_is_not_public_message_link(self):
        message = SimpleNamespace(chat=types.User(id=7, username='ana'), chat_id=7, id=10,
                                  sender_id=7, date=NOW, raw_text='Hola', media=None)
        self.assertIsNone(message_data(message)['url'])

    def test_basic_group_id_prefix_is_not_channel_link(self):
        message = SimpleNamespace(chat=None, chat_id=-100123, id=10,
                                  sender_id=7, date=NOW, raw_text='Hola', media=None)
        self.assertIsNone(message_data(message)['url'])
        message.chat_id = utils.get_peer_id(types.PeerChannel(123))
        self.assertEqual(message_data(message)['url'], 'https://t.me/c/123/10')

    def test_budget_preserves_ids_and_notes_truncation(self):
        result = budget_result({'messages': [{'id': 10, 'text': 'a' * 2000}]}, 1000)
        self.assertTrue(result['text_truncated'])
        self.assertEqual(result['messages'][0]['id'], 10)

    def test_links_and_cursor_validation(self):
        self.assertEqual(parse_link('https://t.me/canal/10'), ('@canal', 10))
        for url in ('https://t.me/+invite', 'https://t.me/c/123/0', 'http://t.me/canal/10'):
            with self.assertRaises(ValueError):
                parse_link(url)
