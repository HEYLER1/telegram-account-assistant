"""Local state: opaque pagination, indexed content and resumable exports."""
import json
import secrets
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.db = sqlite3.connect(directory / 'state.sqlite3')
        (directory / 'state.sqlite3').chmod(0o600)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY, kind TEXT, value TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS content(chat TEXT, message INTEGER, source TEXT, text TEXT, metadata TEXT,
            PRIMARY KEY(chat,message,source));
        CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(chat UNINDEXED,message UNINDEXED,source UNINDEXED,text);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def token(self, kind, value, ttl=86400):
        token = secrets.token_urlsafe(24)
        with self.db:
            self.db.execute('DELETE FROM tokens WHERE expires < ?', (time.time(),))
            self.db.execute('INSERT INTO tokens VALUES (?,?,?,?)',
                            (token, kind, json.dumps(value), time.time() + ttl))
        return token

    def resolve(self, token, kind):
        row = self.db.execute('SELECT value, expires FROM tokens WHERE token=? AND kind=?', (token, kind)).fetchone()
        if not row or row[1] < time.time():
            raise ValueError('Cursor o comprobante inválido o vencido.')
        return json.loads(row[0])

    def consume(self, token):
        with self.db:
            self.db.execute('DELETE FROM tokens WHERE token=?', (token,))

    def index(self, message, text=None, source='telegram'):
        chat, mid = str(message['chat_id']), message['id']
        text = message['text'] if text is None else text
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO content VALUES (?,?,?,?,?)',
                            (chat, mid, source, text, json.dumps(message, ensure_ascii=False)))
            self.db.execute('DELETE FROM content_fts WHERE chat=? AND message=? AND source=?', (chat, mid, source))
            self.db.execute('INSERT INTO content_fts VALUES (?,?,?,?)', (chat, mid, source, text))

    def cached(self, chat, mid, source):
        row = self.db.execute('SELECT text FROM content WHERE chat=? AND message=? AND source=?',
                              (str(chat), mid, source)).fetchone()
        return row[0] if row else None

    def search(self, query, chat=None, limit=30):
        words = query.split()
        if not words:
            raise ValueError('Indica texto para buscar en el índice local.')
        match = ' AND '.join('"' + word.replace('"', '""') + '"' for word in words)
        sql = '''SELECT c.metadata,c.text,c.source FROM content_fts f JOIN content c
                 ON c.chat=f.chat AND c.message=f.message AND c.source=f.source
                 WHERE content_fts MATCH ?'''
        params = [match]
        if chat is not None:
            sql += ' AND c.chat=?'
            params.append(str(chat))
        sql += ' ORDER BY rank LIMIT ?'
        params.append(limit)
        return [{**json.loads(meta), 'indexed_text': text, 'source': source}
                for meta, text, source in self.db.execute(sql, params)]
