import unittest
from telethon.tl.types import Channel, ChatPhotoEmpty
from types import SimpleNamespace
from datetime import datetime, timezone
from telegram_assistant.service import SearchService, bounded_limit, message_data


class FakeClient:
    def __init__(self):
        self.calls = []

    async def iter_messages(self, entity, **kwargs):
        self.calls.append((entity, kwargs))
        yield SimpleNamespace(id=12, chat=Channel(id=123, username='canal', title='Canal', photo=ChatPhotoEmpty(), date=datetime(2026,1,1,tzinfo=timezone.utc)),
                              chat_id=-1000000000123, sender_id=7, date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                              raw_text='factura', media=None)


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_and_chat_search(self):
        client = FakeClient()
        service = SearchService(client)
        result = await service.search('factura')
        self.assertIsNone(client.calls[0][0])
        self.assertEqual(result['messages'][0]['url'], 'https://t.me/canal/12')
        await service.search('factura', '-100123', 5)
        self.assertEqual(client.calls[1], (-100123, {'search': 'factura', 'limit': 5}))

    async def test_empty_search_does_not_request_telegram(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            await SearchService(client).search(' ')
        self.assertEqual(client.calls, [])

    async def test_history_pagination(self):
        client = FakeClient()
        await SearchService(client).history('me', 10, 12)
        self.assertEqual(client.calls, [('me', {'limit': 10, 'offset_id': 12})])

    def test_unbounded_requests_rejected(self):
        for value in (0, 101, -1, True, 1.5):
            with self.assertRaises(ValueError):
                bounded_limit(value)
