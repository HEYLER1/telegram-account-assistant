import argparse
import asyncio
import json
import sys
from .service import connection, SearchService


async def execute(args):
    async with connection(login=args.command == 'login' and not args.qr, qr=args.command == 'login' and args.qr) as client:
        service = SearchService(client)
        if args.command == 'login':
            return {'connected': True, 'message': 'Sesión guardada localmente.'}
        if args.command == 'chats':
            return await service.chats(args.query, args.limit)
        if args.command == 'search':
            return await service.search(args.query, args.chat, args.limit)
        return await service.history(args.chat, args.limit, args.before_id)


def main():
    parser = argparse.ArgumentParser(description='Busca en tu cuenta de Telegram.')
    commands = parser.add_subparsers(dest='command', required=True)
    login = commands.add_parser('login')
    login.add_argument('--qr', action='store_true', help='Vincular con código QR')
    call = commands.add_parser('tool', help='Acceder a todas las funciones desde una sola entrada')
    call.add_argument('action', nargs='?', default='ayuda')
    call.add_argument('--params', default='{}', help='Parámetros como objeto JSON')
    call.add_argument('--budget', type=int, default=24000)
    commands.add_parser('serve')
    chats = commands.add_parser('chats')
    chats.add_argument('query', nargs='?', default='')
    search = commands.add_parser('search')
    search.add_argument('query')
    search.add_argument('--chat')
    history = commands.add_parser('history')
    history.add_argument('chat')
    history.add_argument('--before-id', type=int, default=0)
    for command in (chats, search, history):
        command.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()
    try:
        if args.command == 'serve':
            from .server import mcp
            mcp.run(transport='stdio')
        elif args.command == 'tool':
            from .gateway import Gateway
            gateway = Gateway()
            try:
                result = asyncio.run(gateway.call(args.action, json.loads(args.params), args.budget))
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if not result['ok']:
                    raise SystemExit(1)
            finally:
                gateway.close()
        else:
            print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, indent=2))
    except Exception as error:
        # No imprimir credenciales ni contenido de errores del transporte.
        from telethon.errors import FloodWaitError
        if isinstance(error, FloodWaitError):
            print(f'Telegram solicita esperar {error.seconds} segundos.', file=sys.stderr)
        elif isinstance(error, (ValueError, RuntimeError)):
            print(str(error), file=sys.stderr)
        else:
            print(f'No se pudo completar la operación ({type(error).__name__}).', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
