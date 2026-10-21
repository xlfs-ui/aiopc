"""Postgres backend for the existing parameterized storage contract.

The small-app write lock preserves the same transactional business guarantees
as SQLite BEGIN IMMEDIATE across Render workers and deployments.
"""
import hashlib
import re
import sqlite3
import threading
from contextlib import contextmanager

_slots=threading.BoundedSemaphore(6)
_migration_lock=threading.Lock()
_initialized=set()
WRITE_LOCK=2026102101


class Row(dict):
    def __getitem__(self,key):
        return tuple(self.values())[key] if isinstance(key,int) else super().__getitem__(key)


class Cursor:
    def __init__(self,cursor): self.cursor=cursor
    @property
    def rowcount(self): return self.cursor.rowcount
    def fetchone(self):
        row=self.cursor.fetchone()
        return Row(row) if row is not None else None
    def fetchall(self): return [Row(row) for row in self.cursor.fetchall()]
    def __iter__(self):
        for row in self.cursor: yield Row(row)


def parameters(sql):
    # Replace only placeholders, never quoted literals or parameter contents.
    return re.sub(r"'(?:''|[^'])*'|\?",lambda match:'%s' if match[0]=='?' else match[0],sql).replace('LIMIT -1 OFFSET','OFFSET')


class Connection:
    def __init__(self,connection): self.raw=connection
    def execute(self,sql,params=()):
        import psycopg
        try: return Cursor(self.raw.execute(parameters(sql),params or None))
        except psycopg.IntegrityError:
            # Keep the shared API's existing generic conflict handling.
            raise sqlite3.IntegrityError('Database integrity constraint') from None


def initialize(connection,url):
    fingerprint=hashlib.sha256(url.encode()).hexdigest()
    if fingerprint in _initialized: return
    with _migration_lock:
        if fingerprint in _initialized: return
        from app.storage import SCHEMA, BUSINESS
        with connection.transaction():
            connection.execute('SELECT pg_advisory_xact_lock(%s)',(WRITE_LOCK,))
            connection.execute('CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)')
            row=connection.execute('SELECT MAX(version) AS version FROM schema_versions').fetchone()
            version=row['version'] or 0
            if version>2: raise RuntimeError('Database schema is newer than this application')
            if version<2:
                for statement in SCHEMA:
                    if 'CREATE VIRTUAL TABLE' in statement: continue
                    statement=statement.replace('original BLOB','original BYTEA')
                    if statement.startswith('CREATE TABLE IF NOT EXISTS audit '): statement=statement.replace('id INTEGER PRIMARY KEY','id BIGSERIAL PRIMARY KEY')
                    connection.execute(statement)
                for table,columns in BUSINESS.items():
                    connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({','.join(name+' '+definition for name,definition in columns.items())}, _position INTEGER NOT NULL DEFAULT 0)")
                connection.execute("CREATE TABLE IF NOT EXISTS knowledge_fts (chunk_id TEXT PRIMARY KEY REFERENCES retrieval_chunks(id) ON DELETE CASCADE,title_tokens TEXT NOT NULL,body_tokens TEXT NOT NULL,search_vector TSVECTOR GENERATED ALWAYS AS (setweight(to_tsvector('simple'::regconfig,title_tokens),'A') || setweight(to_tsvector('simple'::regconfig,body_tokens),'B')) STORED)")
                connection.execute('CREATE INDEX IF NOT EXISTS knowledge_search ON knowledge_fts USING GIN(search_vector)')
                connection.execute('CREATE INDEX IF NOT EXISTS ticket_owner ON tickets(owner_id,created_at)')
                connection.execute('CREATE INDEX IF NOT EXISTS ticket_status ON tickets(status,created_at)')
                connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS registration_owner ON registrations(activity_id,owner_id) WHERE owner_id IS NOT NULL')
                connection.execute('INSERT INTO schema_versions VALUES (2) ON CONFLICT DO NOTHING')
        _initialized.add(fingerprint)


@contextmanager
def connect(url,write=False):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row
    if not _slots.acquire(timeout=15): raise RuntimeError('Database connection capacity reached')
    connection=None
    try:
        options=conninfo_to_dict(url)
        if options.get('sslmode') not in ('require','verify-ca','verify-full'): options['sslmode']='require'
        connection=psycopg.connect(**options,connect_timeout=10,row_factory=dict_row,prepare_threshold=None,autocommit=True)
        initialize(connection,url)
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='15000ms'")
            connection.execute("SET LOCAL lock_timeout='15000ms'")
            if write: connection.execute('SELECT pg_advisory_xact_lock(%s)',(WRITE_LOCK,))
            yield Connection(connection)
    finally:
        if connection is not None: connection.close()
        _slots.release()
