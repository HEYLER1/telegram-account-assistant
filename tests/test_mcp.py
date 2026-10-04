import unittest
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_tool_catalog_and_validation_without_login(self):
        root = Path(__file__).resolve().parent.parent
        params = StdioServerParameters(command=str(root / '.venv/bin/telegram-asistente'), args=['serve'])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual([t.name for t in tools.tools], ['telegram'])
                result = await session.call_tool('telegram', {'accion': 'ayuda'})
                self.assertFalse(result.isError)
                self.assertTrue(result.structuredContent['ok'])
                self.assertGreaterEqual(len(result.structuredContent['result']['actions']), 26)
                result = await session.call_tool('telegram', {'accion': 'buscar', 'parametros': {'consulta':'x', 'limite':True}})
                self.assertFalse(result.structuredContent['ok'])
                self.assertEqual(result.structuredContent['error']['code'], 'invalid_parameters')
